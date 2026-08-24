"""One-time codes — the login path suppliers actually use.

§5.2 assumes low-tech users on mid-range Android over patchy 4G. A password is a support
ticket waiting to happen; a six-digit code over WhatsApp is not. The code is short, so the
protections are: hashed at rest, single-use, short TTL, and an attempt counter checked before
comparison so it cannot be brute-forced.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_secret, verify_secret
from app.config import settings
from app.models import OtpChallenge, User


class OtpError(Exception):
    """No live challenge, wrong code, expired, or too many attempts."""


def generate_code() -> str:
    """A zero-padded numeric code. secrets, not random — this is a credential."""
    upper = 10 ** settings.otp_length
    return str(secrets.randbelow(upper)).zfill(settings.otp_length)


def issue_challenge(
    db: Session, destination: str, channel: str, user: User | None = None
) -> tuple[OtpChallenge, str]:
    """Create a challenge and return it with the plaintext code for the notification layer.

    The plaintext is returned, never stored. Any previous live challenge for the same
    destination is consumed, so an old code in an old message cannot still work.
    """
    now = datetime.now(timezone.utc)

    stale = db.scalars(
        select(OtpChallenge).where(
            OtpChallenge.destination == destination,
            OtpChallenge.consumed_at.is_(None),
        )
    ).all()
    for challenge in stale:
        challenge.consumed_at = now

    code = generate_code()
    challenge = OtpChallenge(
        user_id=user.id if user else None,
        destination=destination,
        channel=channel,
        code_hash=hash_secret(code),
        expires_at=now + timedelta(minutes=settings.otp_ttl_minutes),
    )
    db.add(challenge)
    db.flush()
    return challenge, code


def verify_code(db: Session, destination: str, code: str) -> uuid.UUID | None:
    """Consume a challenge, returning the user id it belongs to.

    Raises OtpError on every failure mode with the same message: a caller must not be able to
    tell "no such number" from "wrong code", or the endpoint becomes a way to enumerate which
    factories are registered.
    """
    now = datetime.now(timezone.utc)
    challenge = db.scalars(
        select(OtpChallenge)
        .where(
            OtpChallenge.destination == destination,
            OtpChallenge.consumed_at.is_(None),
        )
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    ).first()

    if challenge is None:
        raise OtpError("Invalid or expired code")

    expires_at = challenge.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < now:
        challenge.consumed_at = now
        raise OtpError("Invalid or expired code")

    if challenge.attempts >= settings.otp_max_attempts:
        challenge.consumed_at = now
        raise OtpError("Invalid or expired code")

    # Count the attempt before checking it, so a crash mid-verify cannot reset the budget.
    challenge.attempts += 1
    db.flush()

    if not verify_secret(challenge.code_hash, code):
        raise OtpError("Invalid or expired code")

    challenge.consumed_at = now
    db.flush()
    return challenge.user_id
