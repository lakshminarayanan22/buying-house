"""The audit trail. §11: you will need "who changed this price and when" in month three."""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import ActivityAction
from app.models.base import Base, JSONVariant, TimestampMixin, uuid_pk


class ActivityLog(Base, TimestampMixin):
    """One row per state change, on every entity, forever.

    `before`/`after` hold only the fields that actually changed, so the row stays small and
    the diff is readable without fetching the entity. Writes go through
    services.activity.record() — never inline — so no code path can forget.
    """

    __tablename__ = "activity_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    # Denormalised so "everything that happened to this supplier" is one indexed scan.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), index=True
    )
    # Kept as text as well: if the user row is ever deleted the trail must still name someone.
    actor_label: Mapped[str | None] = mapped_column(String(200))

    action: Mapped[ActivityAction] = mapped_column(String(40), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONVariant)
    after: Mapped[dict | None] = mapped_column(JSONVariant)

    ip_address: Mapped[str | None] = mapped_column(String(60))

    __table_args__ = (
        Index("ix_activity_log_entity", "entity_type", "entity_id"),
        Index("ix_activity_log_org_created", "org_id", "created_at"),
    )


class Note(Base, TimestampMixin):
    """A comment on any entity.

    `is_internal_only` defaults to True. §4: internal commentary about a supplier must never
    be visible to that supplier, and a default of False would leak the first time somebody
    forgot the flag.
    """

    __tablename__ = "note"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal_only: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    mentions: Mapped[list | None] = mapped_column(JSONVariant)

    __table_args__ = (Index("ix_note_entity", "entity_type", "entity_id"),)


class Task(Base, TimestampMixin):
    """A to-do hung off any entity — the spine of the "my desk" screen (§6.4)."""

    __tablename__ = "task"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="NORMAL", server_default="NORMAL"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="OPEN", server_default="OPEN", index=True
    )
