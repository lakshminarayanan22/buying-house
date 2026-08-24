"""Notification outbox (§7).

Business logic writes rows; a worker dispatches them. That indirection is what makes delivery
retry-safe and auditable, and it is why adding WhatsApp later touches no business code.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import NotificationChannel, NotificationStatus
from app.models.base import Base, JSONVariant, TimestampMixin, uuid_pk


class NotificationTemplate(Base, TimestampMixin):
    """Per-event, per-channel, per-language message bodies.

    Templates live in the database so wording (and the Tamil translation) changes without a
    deploy. Bodies are rendered with simple {placeholder} substitution from the event payload.
    """

    __tablename__ = "notification_template"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )
    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # WhatsApp Cloud API requires pre-approved template names for business-initiated messages.
    provider_template_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        UniqueConstraint(
            "event_key", "channel", "language", name="uq_notification_template_event_channel_lang"
        ),
    )


class NotificationPreference(Base, TimestampMixin):
    """Per-user opt-out for one event/channel pair. Absence of a row means "send"."""

    __tablename__ = "notification_preference"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_key: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("user_id", "event_key", "channel", name="uq_notif_pref_user_event_channel"),
    )


class NotificationOutbox(Base, TimestampMixin):
    """One queued message. Written inside the business transaction, sent outside it."""

    __tablename__ = "notification_outbox"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(String(20), nullable=False, index=True)

    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    # Literal address at send time. Kept separately from the user row so the audit record of
    # "where did this actually go" survives the user later changing their phone number.
    recipient_address: Mapped[str | None] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )

    subject: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONVariant)

    entity_type: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))

    status: Mapped[NotificationStatus] = mapped_column(
        String(20), nullable=False, default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value, index=True,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))

    # Set by the caller for events that must fire at most once (e.g. "cert expiring, T-30, for
    # certificate X"). A unique index on it turns idempotency into a database guarantee rather
    # than a hope about how often the nightly sweep runs.
    dedupe_key: Mapped[str | None] = mapped_column(String(300))

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notification_outbox_dedupe_key"),
        Index("ix_notification_outbox_dispatch", "status", "scheduled_for"),
        Index("ix_notification_outbox_inbox", "recipient_user_id", "channel", "read_at"),
    )
