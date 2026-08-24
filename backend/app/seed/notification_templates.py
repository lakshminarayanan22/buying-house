"""§7 notification templates.

Stored in the database, not in code, so wording changes without a deploy — and so the Tamil
translations are an INSERT rather than a refactor. Only English is populated today; the
`language` column and the fallback in services.notifications are already in place.

WhatsApp bodies are deliberately short and free of markup: they are read on a mid-range
Android in a noisy factory office, and the Cloud API charges per business-initiated message.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import NotificationChannel as C
from app.models import NotificationTemplate
from app.services.notifications import EventKey

# (event_key, channel, subject, body)
TEMPLATES: list[tuple[str, C, str | None, str]] = [
    (
        EventKey.INVITE_SENT, C.EMAIL,
        "{inviter_org} has invited you to {app_name}",
        "Hello {name},\n\n{inviter_org} has invited you to join {app_name} as {role}.\n\n"
        "Set up your account here: {invite_url}\n\nThis link expires on {expires_on}.",
    ),
    (
        EventKey.INVITE_SENT, C.WHATSAPP, None,
        "{app_name}: {inviter_org} has invited you to register your unit. "
        "Open {invite_url} to start. Takes 5 minutes.",
    ),
    (
        EventKey.OTP_CODE, C.WHATSAPP, None,
        "{code} is your {app_name} login code. Valid for {ttl_minutes} minutes. "
        "Do not share it with anyone.",
    ),
    (
        EventKey.OTP_CODE, C.EMAIL,
        "Your {app_name} login code",
        "Your login code is {code}. It is valid for {ttl_minutes} minutes.",
    ),
    (
        EventKey.RESUME_LINK, C.WHATSAPP, None,
        "{app_name}: your profile is saved at {completeness_pct}% complete. "
        "Continue any time from {resume_url} — nothing you entered is lost.",
    ),
    (
        EventKey.SUPPLIER_PROFILE_SUBMITTED, C.EMAIL,
        "{supplier_name} has submitted their profile for review",
        "{supplier_name} ({city}) submitted their profile on {submitted_on}.\n"
        "Completeness: {completeness_pct}%.\n\nReview it here: {review_url}",
    ),
    (
        EventKey.VERIFICATION_APPROVED, C.WHATSAPP, None,
        "Good news — {org_name} is now verified on {app_name}. "
        "You will start receiving enquiries that match your capabilities.",
    ),
    (
        EventKey.VERIFICATION_APPROVED, C.EMAIL,
        "Your {app_name} profile is verified",
        "Hello {name},\n\n{org_name} has been verified. Your profile is now visible for "
        "matching, and you will be notified when an enquiry fits your capabilities.",
    ),
    (
        EventKey.VERIFICATION_NEEDS_INFO, C.WHATSAPP, None,
        "{app_name}: we need a little more information before verifying {org_name}. "
        "Details here: {resume_url}",
    ),
    (
        EventKey.VERIFICATION_NEEDS_INFO, C.EMAIL,
        "More information needed for {org_name}",
        "Hello {name},\n\nBefore we can verify {org_name} we need:\n\n{requested_items}\n\n"
        "You can add these here: {resume_url}",
    ),
    (
        EventKey.VERIFICATION_REJECTED, C.EMAIL,
        "Update on your {app_name} registration",
        "Hello {name},\n\nWe are not able to proceed with {org_name} at this time.\n\n"
        "{reason}\n\nIf you believe this is an error, reply to this email.",
    ),
    (
        # §5.2: incomplete profiles are invisible to the matching engine, so the nudge says
        # exactly what is missing and what it unlocks, rather than "please complete profile".
        EventKey.PROFILE_COMPLETENESS_NUDGE, C.WHATSAPP, None,
        "{app_name}: {org_name} is {completeness_pct}% complete. Add {missing_summary} to start "
        "receiving enquiries. Continue here: {resume_url}",
    ),
    (
        EventKey.CERTIFICATE_EXPIRING, C.EMAIL,
        "{certification} expires in {days_remaining} days",
        "Hello {name},\n\nYour {certification} certificate ({certificate_no}) for {org_name} "
        "expires on {valid_till}.\n\nUpload the renewed certificate here: {upload_url}\n\n"
        "Buyers filter on valid certificates, so an expired one removes you from matching.",
    ),
    (
        EventKey.CERTIFICATE_EXPIRING, C.WHATSAPP, None,
        "{app_name}: your {certification} expires on {valid_till}. Upload the renewal at "
        "{upload_url} to stay eligible for {certification} enquiries.",
    ),
    (
        EventKey.CERTIFICATE_EXPIRED, C.EMAIL,
        "{certification} has expired for {org_name}",
        "Your {certification} certificate expired on {valid_till} and your verification badge "
        "for it has been removed. Upload the renewal here: {upload_url}",
    ),
]


def seed_notification_templates(db: Session, language: str = "en") -> int:
    """Idempotent upsert of the template set for one language."""
    written = 0
    for event_key, channel, subject, body in TEMPLATES:
        row = db.scalars(
            select(NotificationTemplate).where(
                NotificationTemplate.event_key == event_key,
                NotificationTemplate.channel == channel,
                NotificationTemplate.language == language,
            )
        ).first()
        if row is None:
            row = NotificationTemplate(
                event_key=event_key, channel=channel, language=language,
                subject=subject, body=body,
            )
            db.add(row)
        else:
            row.subject, row.body = subject, body
        written += 1

    db.commit()
    return written
