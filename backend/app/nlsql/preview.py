"""Execute a change inside a transaction, capture the real diff, roll back.

The user-visible behaviour is "it made the change, here is what changed, confirm?". The
difference from actually applying it is that the transaction is never committed, so there is
no window in which other users, other queries, or the notification worker can observe wrong
data. What the reviewer sees is not a prediction — it is the rows the statement actually
touched, read back from the database.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.enums import ActivityAction
from app.models import Base, ChangeRequest
from app.nlsql.guard import Kind, ValidatedStatement, validate
from app.rbac import Principal
from app.services import activity

# Above this, a preview refuses unless the caller explicitly opts in. A statement that touches
# 4,000 rows is usually a WHERE clause that did not do what its author thought.
DEFAULT_MAX_ROWS = 200
PREVIEW_TTL_MINUTES = 30


class ChangeConflict(Exception):
    """The targeted rows changed between preview and confirm. The API maps this to 409."""


class ChangeTooLarge(Exception):
    """More rows than the caller agreed to touch."""


@dataclass
class PreviewResult:
    change_request: ChangeRequest
    statement: ValidatedStatement


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _rows_to_dicts(result) -> list[dict]:
    keys = list(result.keys())
    return [{k: _jsonable(v) for k, v in zip(keys, row)} for row in result.fetchall()]


def _primary_key(table_name: str) -> list[str]:
    """The real primary key from the mapped metadata, so rows are matched, not guessed.

    Most tables key on `id`, but supplier_profile and brand_profile key on org_id — pairing
    before and after rows by position instead would mislabel a diff the moment a statement
    touches more than one row.
    """
    table = Base.metadata.tables.get(table_name)
    if table is None:
        return ["id"]
    return [c.name for c in table.primary_key.columns] or ["id"]


def _key_of(row: dict, pk_columns: list[str]) -> tuple:
    return tuple(row.get(col) for col in pk_columns)


def _fingerprint(rows: list[dict]) -> str:
    """A stable hash of the before-image, used as the optimistic-concurrency check."""
    payload = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _build_diff(
    kind: Kind, before: list[dict], after: list[dict], pk_columns: list[str]
) -> list[dict]:
    """Per-row, per-column changes — the highlight the confirmation screen renders."""
    if kind == Kind.INSERT:
        return [
            {"pk": _key_of(row, pk_columns), "operation": "INSERT", "after": row, "changes": {}}
            for row in after
        ]
    if kind == Kind.DELETE:
        return [
            {"pk": _key_of(row, pk_columns), "operation": "DELETE", "before": row, "changes": {}}
            for row in before
        ]

    before_by_key = {_key_of(r, pk_columns): r for r in before}
    diff = []
    for row in after:
        key = _key_of(row, pk_columns)
        old = before_by_key.get(key, {})
        changes = {
            col: {"before": old.get(col), "after": value}
            for col, value in row.items()
            # updated_at moves on every write; listing it as a change hides the real ones.
            if col != "updated_at" and old.get(col) != value
        }
        diff.append({
            "pk": key, "operation": "UPDATE", "before": old, "after": row, "changes": changes,
        })
    return diff


def _execute_and_capture(
    db: Session, statement: ValidatedStatement
) -> tuple[list[dict], list[dict]]:
    """Run the statement and read back what it touched. Caller controls the transaction."""
    before: list[dict] = []
    if statement.before_sql:
        before = _rows_to_dicts(db.execute(text(statement.before_sql)))

    result = db.execute(text(statement.exec_sql))
    after = _rows_to_dicts(result) if statement.kind != Kind.DELETE else []
    return before, after


def preview_sql(
    db: Session,
    *,
    prompt: str,
    sql: str,
    actor: Principal,
    planner_backend: str = "manual",
    planner_model: str | None = None,
    explanation: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> PreviewResult:
    """Validate, run inside a SAVEPOINT, capture the diff, roll back, store the proposal."""
    statement = validate(sql)

    savepoint = db.begin_nested()
    try:
        before, after = _execute_and_capture(db, statement)
        affected = len(after) if statement.kind != Kind.DELETE else len(before)
        if affected > max_rows:
            raise ChangeTooLarge(
                f"This would affect {affected} rows, more than the {max_rows}-row limit. "
                "Narrow the condition, or re-run with a higher limit if that is intended."
            )
        pk_columns = _primary_key(statement.table)
        diff = _build_diff(statement.kind, before, after, pk_columns)
    finally:
        # Always. The preview must leave the database exactly as it found it, including when
        # the statement raised or the row count was refused.
        savepoint.rollback()

    change = ChangeRequest(
        prompt=prompt,
        generated_sql=statement.sql,
        explanation=explanation,
        planner_backend=planner_backend,
        planner_model=planner_model,
        target_table=statement.table,
        statement_kind=statement.kind.value,
        affected_count=affected,
        before_rows=before or None,
        after_rows=after or None,
        diff=[{**d, "pk": [str(p) for p in d["pk"]]} for d in diff],
        before_fingerprint=_fingerprint(before),
        status="PREVIEWED",
        requested_by_user_id=actor.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=PREVIEW_TTL_MINUTES),
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    return PreviewResult(change_request=change, statement=statement)


def apply_change(db: Session, change: ChangeRequest, actor: Principal) -> ChangeRequest:
    """Commit a previewed change, after confirming the rows still look as they did.

    The re-check is the point. Between preview and confirm somebody else may have edited the
    same supplier; applying anyway would silently overwrite their work with a diff the reviewer
    never actually saw.
    """
    if change.status != "PREVIEWED":
        raise ChangeConflict(f"This change is already {change.status.lower()}.")

    expires_at = change.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            change.status = "EXPIRED"
            db.commit()
            raise ChangeConflict("This preview has expired. Run it again to see a fresh diff.")

    statement = validate(change.generated_sql)

    if statement.before_sql:
        current = _rows_to_dicts(db.execute(text(statement.before_sql)))
        if _fingerprint(current) != change.before_fingerprint:
            change.status = "CONFLICTED"
            change.rejection_reason = (
                "The targeted rows changed after the preview was generated."
            )
            db.commit()
            raise ChangeConflict(
                "Those rows have changed since you previewed this. Re-run it to see the "
                "current diff before confirming."
            )

    before, after = _execute_and_capture(db, statement)

    change.before_rows = before or None
    change.after_rows = after or None
    change.status = "APPLIED"
    change.applied_at = datetime.now(timezone.utc)

    # One audit entry per affected row, not one per statement: "who changed this price and
    # when" has to be answerable from the row, not from a SQL string someone has to re-read.
    pk_columns = _primary_key(statement.table)
    for entry in _build_diff(statement.kind, before, after, pk_columns):
        raw_pk = entry["pk"][0] if entry["pk"] else None
        try:
            entity_id = uuid.UUID(str(raw_pk)) if raw_pk is not None else None
        except (ValueError, AttributeError):
            entity_id = None

        row = entry.get("after") or entry.get("before") or {}
        org_id = None
        raw_org = row.get("org_id") if statement.table != "organization" else row.get("id")
        if raw_org:
            try:
                org_id = uuid.UUID(str(raw_org))
            except ValueError:
                org_id = None

        activity.record(
            db,
            entity_type=statement.table,
            entity_id=entity_id,
            org_id=org_id,
            action=ActivityAction.UPDATE,
            actor=actor,
            summary=f'Natural-language edit: "{change.prompt[:180]}"',
            before=entry.get("before"),
            after=entry.get("after"),
        )

    db.commit()
    db.refresh(change)
    return change


def discard_change(db: Session, change: ChangeRequest, reason: str | None = None) -> ChangeRequest:
    if change.status != "PREVIEWED":
        raise ChangeConflict(f"This change is already {change.status.lower()}.")
    change.status = "DISCARDED"
    change.rejection_reason = reason
    db.commit()
    db.refresh(change)
    return change
