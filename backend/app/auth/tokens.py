"""JWTs for sessions, invite magic links, and supplier save-and-resume links.

Three token types, one secret, distinguished by a `type` claim that is checked on every
verify — a resume link must never be accepted as a session.

Session tokens carry `tv` (the user's token_version). Bumping User.token_version invalidates
every outstanding session for that user, which is what makes "disable this user" immediate
rather than eventual.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


class TokenError(Exception):
    """Invalid signature, wrong type, or malformed token."""


class TokenExpiredError(TokenError):
    """Well-formed and correctly signed, but past its expiry."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc


def _require_type(payload: dict, expected: str) -> dict:
    if payload.get("type") != expected:
        raise TokenError(f"not a {expected} token")
    return payload


# --------------------------------------------------------------------------- session
def create_session_token(user_id: uuid.UUID, token_version: int) -> str:
    now = _now()
    return _encode({
        "type": "session",
        "sub": str(user_id),
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_token_ttl_hours)).timestamp()),
    })


def verify_session_token(token: str) -> tuple[uuid.UUID, int]:
    payload = _require_type(_decode(token), "session")
    try:
        return uuid.UUID(payload["sub"]), int(payload.get("tv", 0))
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed session token") from exc


# --------------------------------------------------------------------------- invite
def create_invite_token(invite_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    """A magic link for a brand or supplier invitation (§5.1).

    org_id and role live in the signed payload, never in the request body. That is what stops
    an invitee promoting themselves to a different org or a higher role on acceptance.
    """
    now = _now()
    return _encode({
        "type": "invite",
        "sub": str(invite_id),
        "org": str(org_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.invite_token_ttl_days)).timestamp()),
    })


def verify_invite_token(token: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    payload = _require_type(_decode(token), "invite")
    try:
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["org"]), payload["role"]
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed invite token") from exc


# --------------------------------------------------------------------------- resume
def create_resume_token(org_id: uuid.UUID) -> str:
    """§5.2 save-and-resume: never lose a half-filled supplier form.

    Deliberately long-lived and low-privilege — it authorises editing one draft profile and
    nothing else, so a link sitting in a WhatsApp thread for three weeks stays useful without
    being a session.
    """
    now = _now()
    return _encode({
        "type": "resume",
        "org": str(org_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.resume_token_ttl_days)).timestamp()),
    })


def verify_resume_token(token: str) -> uuid.UUID:
    payload = _require_type(_decode(token), "resume")
    try:
        return uuid.UUID(payload["org"])
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed resume token") from exc
