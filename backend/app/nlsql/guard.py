"""What the natural-language editor is allowed to do, enforced on the parsed statement.

This is the security boundary. It works on a sqlglot AST rather than on regexes, because
string matching on SQL is defeated by comments, casing, nesting and whitespace — and it is
applied to the generated SQL regardless of what produced it, so a prompt injection that
convinces the model to write `DROP TABLE` still gets rejected here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import sqlglot
from sqlglot import exp

DIALECT = "postgres"


class SqlRejected(Exception):
    """The statement is outside what this feature may do. The API maps this to 400."""


class Kind(StrEnum):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


# Tables the editor may write. An allowlist, not a denylist: a table added to the schema next
# month is unreachable until someone deliberately adds it here.
WRITABLE_TABLES = frozenset({
    "organization",
    "contact",
    "brand_profile",
    "brand_category",
    "brand_target_market",
    "brand_required_certification",
    "brand_excluded_country",
    "supplier_profile",
    "supplier_process",
    "supplier_capability",
    "supplier_capability_fibre",
    "supplier_capability_construction",
    "supplier_machine",
    "supplier_certification",
    "supplier_compliance",
    "supplier_capacity_calendar",
    "supplier_export_market",
    "supplier_reference",
    "reference_item",
    "reference_alias",
    "unmapped_term",
    "note",
    "task",
})

# Readable in a WHERE clause or subquery but never written — you may need to say "suppliers who
# have never been sent an RFQ", without being able to edit the outbox.
READABLE_TABLES = WRITABLE_TABLES | frozenset({
    "app_user",
    "document",
    "supplier_performance",
    "import_batch",
    "notification_outbox",
})

# Never writable, and the reason each one is on the list:
#
#   activity_log            an editable audit trail is not an audit trail
#   app_user                holds password hashes and the role column — an UPDATE here is
#                           privilege escalation in one statement
#   otp_challenge           live credentials
#   org_invite              invite tokens
#   brand_supplier_reveal   the identity gate; the entire commercial model rests on it
#   supplier_performance    computed from transactions; hand-editing it corrupts the very
#                           signal the Phase 6 agent is supposed to learn from
#   alembic_version         schema state
NEVER_WRITABLE = frozenset({
    "activity_log",
    "app_user",
    "otp_challenge",
    "org_invite",
    "brand_supplier_reveal",
    "supplier_performance",
    "alembic_version",
    "change_request",
})

# Functions that read files, sleep, open connections, or run shell commands. None of them have
# any business in a record edit.
BANNED_FUNCTIONS = frozenset({
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "dblink", "dblink_exec", "dblink_connect",
    "lo_import", "lo_export", "copy",
    "pg_terminate_backend", "pg_cancel_backend",
    "set_config", "current_setting",
    "query_to_xml", "xmlparse",
})


@dataclass
class ValidatedStatement:
    """A statement that passed every check, plus the queries needed to preview it."""

    kind: Kind
    table: str
    sql: str
    # SELECT over the same rows the statement targets, used to capture the before-image and,
    # at confirm time, to detect that they changed underneath us.
    before_sql: str | None
    # The statement with RETURNING * appended, so the after-image comes back from the write
    # itself rather than from a second query that might match different rows.
    exec_sql: str
    tables_read: frozenset[str] = field(default_factory=frozenset)


def _table_names(node: exp.Expression) -> set[str]:
    names = set()
    for table in node.find_all(exp.Table):
        if table.name:
            names.add(table.name.lower())
    return names


def _check_functions(node: exp.Expression) -> None:
    for func in node.find_all(exp.Anonymous):
        name = (func.this or "").lower() if isinstance(func.this, str) else ""
        if name in BANNED_FUNCTIONS:
            raise SqlRejected(f"The function {name}() is not permitted here.")
    for func in node.find_all(exp.Func):
        name = getattr(func, "sql_name", lambda: "")()
        if isinstance(name, str) and name.lower() in BANNED_FUNCTIONS:
            raise SqlRejected(f"The function {name.lower()}() is not permitted here.")


def validate(sql: str) -> ValidatedStatement:
    """Parse and check one statement, returning the queries needed to preview it."""
    if not sql or not sql.strip():
        raise SqlRejected("No statement was generated.")

    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except Exception as exc:  # sqlglot raises several parse error types
        raise SqlRejected(f"That is not valid SQL: {exc}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        # Chaining is how a benign-looking edit smuggles in a second, less benign one.
        raise SqlRejected(
            f"Exactly one statement is allowed; this has {len(statements)}."
        )

    node = statements[0]

    if isinstance(node, exp.Insert):
        kind = Kind.INSERT
    elif isinstance(node, exp.Update):
        kind = Kind.UPDATE
    elif isinstance(node, exp.Delete):
        kind = Kind.DELETE
    else:
        raise SqlRejected(
            "Only INSERT, UPDATE and DELETE on records are allowed. Schema changes belong in "
            "an Alembic migration, where they are reviewed and reversible."
        )

    # A CTE can hide DML: WITH x AS (DELETE FROM ... RETURNING *) SELECT * FROM x.
    for cte in node.find_all(exp.CTE):
        if any(isinstance(n, (exp.Insert, exp.Update, exp.Delete)) for n in cte.walk()):
            raise SqlRejected("Data-modifying CTEs are not allowed.")

    _check_functions(node)

    target = node.find(exp.Table)
    if target is None or not target.name:
        raise SqlRejected("Could not determine which table this statement writes to.")
    table = target.name.lower()

    if table in NEVER_WRITABLE:
        raise SqlRejected(
            f"'{table}' is never writable from here. "
            + {
                "activity_log": "An editable audit trail is not an audit trail.",
                "app_user": "User accounts and roles are changed through the console, "
                            "where the permission checks apply.",
                "brand_supplier_reveal": "Identity reveals are a deliberate, logged decision.",
                "supplier_performance": "These are computed from real transactions; editing "
                                        "them corrupts the data the matching engine learns from.",
            }.get(table, "")
        )
    if table not in WRITABLE_TABLES:
        raise SqlRejected(f"'{table}' is not a table this feature may write to.")

    referenced = _table_names(node)
    illegal_reads = referenced - READABLE_TABLES
    if illegal_reads:
        raise SqlRejected(
            f"Cannot reference {', '.join(sorted(illegal_reads))} here."
        )

    where = node.args.get("where")
    if kind in (Kind.UPDATE, Kind.DELETE) and where is None:
        raise SqlRejected(
            f"This {kind} has no WHERE clause, so it would affect every row in '{table}'. "
            "Add a condition."
        )

    before_sql = None
    if kind in (Kind.UPDATE, Kind.DELETE):
        # The same rows the statement targets, read before it runs. Built from the parsed WHERE
        # rather than by string surgery, so it cannot drift from the statement it describes.
        before = exp.Select().select(exp.Star()).from_(exp.to_table(table))
        before.set("where", where.copy())
        before_sql = before.sql(dialect=DIALECT)

    exec_node = node.copy()
    if kind != Kind.DELETE:
        exec_node.set("returning", exp.Returning(expressions=[exp.Star()]))
    exec_sql = exec_node.sql(dialect=DIALECT)

    return ValidatedStatement(
        kind=kind,
        table=table,
        sql=node.sql(dialect=DIALECT),
        before_sql=before_sql,
        exec_sql=exec_sql,
        tables_read=frozenset(referenced),
    )
