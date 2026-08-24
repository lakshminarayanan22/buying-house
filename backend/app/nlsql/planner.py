"""Turn an English request into one candidate SQL statement.

The planner is deliberately the least trusted part of this feature. Everything it produces is
re-validated by guard.py and previewed in a rolled-back transaction before anyone can commit
it, so the prompt is an aid to usefulness, not a security control.

Two design choices worth stating:

  * The schema handed to the model is generated from the live SQLAlchemy metadata, not written
    by hand. A hand-maintained schema blurb drifts, and a model that invents a column produces
    a confusing failure instead of a clear one.
  * The model may return `needs_clarification` instead of SQL. For a tool that edits records,
    "I am not sure which supplier you mean" is a far better answer than a confident guess at
    one — and without an explicit way to say so, a model will always produce *something*.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Base
from app.nlsql.guard import READABLE_TABLES, WRITABLE_TABLES

logger = logging.getLogger(__name__)


class PlannerUnavailable(Exception):
    """No planner is configured. The API maps this to 503."""


class NeedsClarification(Exception):
    """The request was too ambiguous to turn into a statement safely."""


class PlannedChange(BaseModel):
    """What the model is asked to return."""

    needs_clarification: bool = Field(
        description=(
            "True when the request is ambiguous, names something that cannot be identified "
            "from the schema, or could reasonably mean more than one change. Prefer this over "
            "guessing: a wrong UPDATE is worse than a follow-up question."
        )
    )
    clarifying_question: str | None = Field(
        default=None, description="The single most useful question to ask. Required when needs_clarification."
    )
    sql: str | None = Field(
        default=None,
        description=(
            "Exactly one PostgreSQL INSERT, UPDATE or DELETE statement. No trailing semicolon, "
            "no RETURNING clause, no CTE. UPDATE and DELETE must have a WHERE clause."
        ),
    )
    explanation: str | None = Field(
        default=None,
        description="One or two plain sentences describing what the statement changes and which rows it targets.",
    )


# Credential columns are omitted from the schema entirely. The model has no legitimate reason
# to reference them, and a column name it never sees is one it cannot be talked into using.
_HIDDEN_COLUMNS = frozenset({"password_hash", "code_hash", "token_hash", "token_version"})


def describe_schema(tables: frozenset[str] | None = None) -> str:
    """Render the schema from live metadata, so the prompt cannot drift from the database."""
    from sqlalchemy.dialects import postgresql

    dialect = postgresql.dialect()
    wanted = tables or READABLE_TABLES
    lines: list[str] = []

    for name in sorted(wanted):
        table = Base.metadata.tables.get(name)
        if table is None:
            continue
        writable = "writable" if name in WRITABLE_TABLES else "READ-ONLY"
        lines.append(f"{name} ({writable})")
        for column in table.columns:
            if column.name in _HIDDEN_COLUMNS:
                continue
            # Compile against the Postgres dialect: the generic repr renders UUID as CHAR(32),
            # which would teach the model the wrong literal syntax.
            try:
                type_name = column.type.compile(dialect=dialect)
            except Exception:  # noqa: BLE001 - an uncompilable type should not break the prompt
                type_name = str(column.type)
            parts = [f"  {column.name} {type_name}"]
            if not column.nullable:
                parts.append("NOT NULL")
            for fk in column.foreign_keys:
                parts.append(f"-> {fk.target_fullname}")
            lines.append(" ".join(parts))
        lines.append("")

    return "\n".join(lines)


SYSTEM_PROMPT = """\
You translate a request from a sourcing team into exactly one PostgreSQL statement against \
the buying-house database.

Rules:
- Emit exactly one INSERT, UPDATE or DELETE. Never DDL, never SELECT, never multiple statements.
- UPDATE and DELETE must always have a WHERE clause.
- Never write to a table marked READ-ONLY, and never to app_user, activity_log, \
brand_supplier_reveal or supplier_performance.
- Do not add a RETURNING clause; the caller adds one.
- Taxonomy values (processes, categories, fibres, certifications, countries, currencies) live \
in reference_item, namespaced by `domain`, and are referenced by id. To match one by name, \
join or subquery on reference_item with the right domain rather than inventing an id.
- Text matching on names should be case-insensitive (lower(col) = lower('x')) unless the user \
gives an exact identifier.
- Prefer targeting rows by id when the user gives one.

Set needs_clarification when:
- more than one organization, supplier or record could match the description
- the request names a value you cannot map to a column or a taxonomy entry
- the request implies a schema change rather than a record change
- the request would affect a large or unbounded set of rows and the user did not clearly say so

Asking one short question is always better than guessing. The statement you produce will be \
shown to a human with its real before/after rows before anything is committed, but a plausible \
wrong statement wastes their attention and risks being approved.
"""


def plan(db: Session, prompt: str, *, extra_context: str | None = None) -> tuple[PlannedChange, str]:
    """Return the planned change and the model id that produced it."""
    backend = settings.nlsql_backend
    if backend == "claude":
        return _plan_with_claude(prompt, extra_context)
    raise PlannerUnavailable(
        "No natural-language planner is configured. Set NLSQL_BACKEND=claude and "
        "ANTHROPIC_API_KEY, or send SQL directly to the preview endpoint."
    )


def _plan_with_claude(prompt: str, extra_context: str | None) -> tuple[PlannedChange, str]:
    import anthropic

    if not settings.anthropic_api_key:
        raise PlannerUnavailable("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    schema = describe_schema()

    user_content = f"Schema:\n\n{schema}\n\nRequest:\n{prompt}"
    if extra_context:
        user_content += f"\n\nAdditional context:\n{extra_context}"

    response = client.messages.parse(
        model=settings.nlsql_model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_content}],
        output_format=PlannedChange,
    )

    planned = response.parsed_output
    if planned.needs_clarification:
        raise NeedsClarification(
            planned.clarifying_question or "That request is ambiguous — can you be more specific?"
        )
    if not planned.sql:
        raise NeedsClarification("No statement could be produced for that request.")

    return planned, settings.nlsql_model
