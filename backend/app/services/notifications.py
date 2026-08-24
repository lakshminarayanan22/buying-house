"""Notification outbox writer and dispatcher (§7).

Business code calls `enqueue()` inside its own transaction. A worker calls `dispatch_pending()`
outside it. Nothing in a request path ever talks to an email or WhatsApp API — that is what
makes delivery retry-safe, auditable, and replaceable.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import NotificationChannel, NotificationStatus
from app.models import (
    NotificationOutbox,
    NotificationPreference,
    NotificationTemplate,
    User,
)

logger = logging.getLogger(__name__)


class EventKey:
    """Event names from the §7 table. Constants, so a typo fails at import, not at send time."""

    INVITE_SENT = "invite.sent"
    OTP_CODE = "auth.otp_code"
    SUPPLIER_PROFILE_SUBMITTED = "supplier.profile_submitted"
    VERIFICATION_APPROVED = "verification.approved"
    VERIFICATION_NEEDS_INFO = "verification.needs_info"
    VERIFICATION_REJECTED = "verification.rejected"
    PROFILE_COMPLETENESS_NUDGE = "supplier.completeness_nudge"
    CERTIFICATE_EXPIRING = "certificate.expiring"
    CERTIFICATE_EXPIRED = "certificate.expired"
    RESUME_LINK = "supplier.resume_link"


def _render(template: str, payload: dict) -> str:
    """Simple {placeholder} substitution. A missing key leaves the placeholder visible rather
    than raising — a half-rendered reminder is better than a notification that never sends."""
    out = template
    for key, value in payload.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _preference_allows(
    db: Session, user_id: uuid.UUID, event_key: str, channel: NotificationChannel
) -> bool:
    pref = db.scalars(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.event_key == event_key,
            NotificationPreference.channel == channel,
        )
    ).first()
    return True if pref is None else pref.enabled


def _address_for(user: User, channel: NotificationChannel) -> str | None:
    if channel == NotificationChannel.EMAIL:
        return user.email
    if channel == NotificationChannel.WHATSAPP:
        return user.whatsapp or user.phone
    return None  # IN_APP is delivered by user_id, not by an address.


def enqueue(
    db: Session,
    *,
    event_key: str,
    user: User | None,
    channels: list[NotificationChannel],
    payload: dict,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    address_override: str | None = None,
    language: str | None = None,
) -> list[NotificationOutbox]:
    """Queue one event across channels. Rendering happens now so the worker stays dumb.

    Channels the user has opted out of, or has no address for, are skipped silently — a
    supplier without an email address should still get the WhatsApp message.
    """
    lang = language or (user.language_pref if user else settings.default_language)
    queued: list[NotificationOutbox] = []

    for channel in channels:
        if user is not None and not _preference_allows(db, user.id, event_key, channel):
            continue

        address = address_override or (_address_for(user, channel) if user else None)
        if channel != NotificationChannel.IN_APP and not address:
            continue

        template = db.scalars(
            select(NotificationTemplate).where(
                NotificationTemplate.event_key == event_key,
                NotificationTemplate.channel == channel,
                NotificationTemplate.language == lang,
                NotificationTemplate.is_active.is_(True),
            )
        ).first()
        # Fall back to the default language before giving up: a missing Tamil template should
        # send English, not nothing.
        if template is None and lang != settings.default_language:
            template = db.scalars(
                select(NotificationTemplate).where(
                    NotificationTemplate.event_key == event_key,
                    NotificationTemplate.channel == channel,
                    NotificationTemplate.language == settings.default_language,
                    NotificationTemplate.is_active.is_(True),
                )
            ).first()
        if template is None:
            logger.warning("no template for %s/%s/%s", event_key, channel, lang)
            continue

        row = NotificationOutbox(
            event_key=event_key,
            channel=channel,
            recipient_user_id=user.id if user else None,
            recipient_address=address,
            language=lang,
            subject=_render(template.subject, payload) if template.subject else None,
            body=_render(template.body, payload),
            payload=payload,
            entity_type=entity_type,
            entity_id=entity_id,
            # Scope the dedupe key by channel so one key can cover a multi-channel event.
            dedupe_key=f"{dedupe_key}:{channel.value}" if dedupe_key else None,
            status=NotificationStatus.PENDING,
        )
        db.add(row)
        queued.append(row)

    return queued


# --------------------------------------------------------------------------- dispatch
def _send_console(row: NotificationOutbox) -> str:
    logger.info(
        "[%s -> %s] %s\n%s", row.channel, row.recipient_address or row.recipient_user_id,
        row.subject or row.event_key, row.body,
    )
    return f"console-{row.id}"


def _sender_for(channel: NotificationChannel):
    """Resolve the dispatcher for a channel.

    Only the console backend ships today. Adding Resend or the WhatsApp Cloud API is a new
    branch here and nothing else — no business code knows how a message leaves the building.
    """
    if channel == NotificationChannel.IN_APP:
        return lambda row: f"in-app-{row.id}"
    if channel == NotificationChannel.EMAIL and settings.email_backend == "console":
        return _send_console
    if channel == NotificationChannel.WHATSAPP and settings.whatsapp_backend == "console":
        return _send_console
    return _send_console


def dispatch_pending(db: Session, limit: int = 100, max_attempts: int = 5) -> int:
    """Send queued messages. Called by the worker; returns how many were sent."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status == NotificationStatus.PENDING,
            NotificationOutbox.attempts < max_attempts,
        )
        .order_by(NotificationOutbox.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()

    sent = 0
    for row in rows:
        if row.scheduled_for is not None:
            scheduled = row.scheduled_for
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            if scheduled > now:
                continue

        row.attempts += 1
        try:
            row.provider_message_id = _sender_for(NotificationChannel(row.channel))(row)
            row.status = NotificationStatus.SENT
            row.sent_at = datetime.now(timezone.utc)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - one bad message must not stop the queue
            row.last_error = str(exc)[:2000]
            if row.attempts >= max_attempts:
                row.status = NotificationStatus.FAILED
            logger.exception("notification %s failed", row.id)

    db.commit()
    return sent
