"""Outgoing email, best effort.

Only two messages exist — "someone is waiting for access" to the admins, and "you're in" to the
person approved. Neither is load-bearing: the Team page shows every pending request whether or
not a mail arrived, so a failed send is logged and swallowed rather than allowed to break the
sign-in or approval that triggered it. Callers hand these to FastAPI BackgroundTasks, so the
person clicking never waits on an SMTP handshake either.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: tuple[str, ...]
    subject: str
    body: str


def send(email: Email) -> bool:
    """Send, or log in console mode. Returns whether it went; never raises."""
    if not email.to:
        return False

    if settings.email_backend.lower() != "smtp":
        logger.info("email (console backend, not sent)\nTo: %s\nSubject: %s\n\n%s",
                    ", ".join(email.to), email.subject, email.body)
        return True

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = ", ".join(email.to)
    message["Subject"] = email.subject
    message.set_content(email.body)

    try:
        with smtplib.SMTP(settings.smtp_host or "smtp.gmail.com", settings.smtp_port,
                          timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("email to %s failed: %s", ", ".join(email.to), exc)
        return False
