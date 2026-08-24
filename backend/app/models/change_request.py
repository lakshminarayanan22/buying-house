"""A proposed record change, its previewed diff, and its eventual outcome."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONVariant, TimestampMixin, uuid_pk


class ChangeRequest(Base, TimestampMixin):
    """One natural-language edit: what was asked, what SQL it became, what it would touch.

    The row is written at preview time and is the only thing that carries state between the
    preview and the confirm — the diff shown to the user and the diff applied on confirm come
    from the same record, so they cannot diverge.

    `before_rows` is kept after the change is applied. It is what makes a confirmed change
    explainable three months later, and what a revert would be built from.
    """

    __tablename__ = "change_request"

    id: Mapped[uuid.UUID] = uuid_pk()

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    planner_backend: Mapped[str] = mapped_column(String(30), nullable=False)
    planner_model: Mapped[str | None] = mapped_column(String(60))

    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    statement_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    before_rows: Mapped[list | None] = mapped_column(JSONVariant)
    after_rows: Mapped[list | None] = mapped_column(JSONVariant)
    # [{"pk": ..., "changes": {"col": {"before": x, "after": y}}}] — the highlight the UI renders.
    diff: Mapped[list | None] = mapped_column(JSONVariant)

    # Fingerprint of the before-image. Re-computed at confirm time; a mismatch means somebody
    # else changed those rows since the preview, and the change is refused rather than applied
    # against data the reviewer never saw.
    before_fingerprint: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PREVIEWED", server_default="PREVIEWED", index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), index=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A preview holds no locks and expires, so a stale proposal cannot be confirmed days later.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_change_request_status_created", "status", "created_at"),)
