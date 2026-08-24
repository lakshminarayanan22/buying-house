"""The one way to write an audit trail entry.

§11: skipping the activity log is a project killer, and the reason is always the same — it
gets written inline at three call sites and forgotten at the other thirty. `record()` is the
only writer, and `record_changes()` computes the diff itself so no caller has to remember what
the row looked like before.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.enums import ActivityAction
from app.models import ActivityLog
from app.rbac import Principal

# Never logged, even in a diff: a password hash or an OTP hash in the audit trail is a
# credential leak with a long retention policy.
_REDACTED_FIELDS = {"password_hash", "code_hash", "token_hash", "secret"}


def _clean(value: Any) -> Any:
    """Make a column value JSON-safe without pulling in a serializer."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action: ActivityAction,
    actor: Principal | None = None,
    actor_label: str | None = None,
    org_id: uuid.UUID | None = None,
    summary: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        entity_type=entity_type,
        entity_id=entity_id,
        org_id=org_id,
        actor_user_id=actor.user_id if actor else None,
        actor_label=actor_label or (str(actor.role) if actor else "system"),
        action=action,
        summary=summary,
        before={k: _clean(v) for k, v in (before or {}).items()} or None,
        after={k: _clean(v) for k, v in (after or {}).items()} or None,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry


def record_changes(
    db: Session,
    instance,
    *,
    actor: Principal | None = None,
    action: ActivityAction = ActivityAction.UPDATE,
    summary: str | None = None,
) -> ActivityLog | None:
    """Log only the fields that actually changed on a dirty ORM instance.

    Call before commit. Returns None when nothing changed, so a no-op save does not litter the
    trail with empty entries.
    """
    state = inspect(instance)
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}

    for attr in state.mapper.column_attrs:
        key = attr.key
        if key in _REDACTED_FIELDS:
            continue
        history = state.attrs[key].history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        if old == new:
            continue
        before[key] = old
        after[key] = new

    if not after:
        return None

    entity_id = getattr(instance, "id", None)
    org_id = getattr(instance, "org_id", None)
    if type(instance).__name__ == "Organization":
        org_id = instance.id

    return record(
        db,
        entity_type=type(instance).__name__,
        entity_id=entity_id,
        action=action,
        actor=actor,
        org_id=org_id,
        summary=summary,
        before=before,
        after=after,
    )
