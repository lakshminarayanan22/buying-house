"""Password hashing. Three or four internal users, so this is all the auth surface there is."""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(hashed: str | None, plain: str) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ----------------------------------------------------------------------- sessions
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


class TokenError(Exception):
    """Invalid, expired, or not a session token."""


def create_session_token(user_id: uuid.UUID, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"type": "session", "sub": str(user_id), "tv": token_version,
         "iat": int(now.timestamp()),
         "exp": int((now + timedelta(hours=settings.session_token_ttl_hours)).timestamp())},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


def verify_session_token(token: str) -> tuple[uuid.UUID, int]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != "session":
        raise TokenError("not a session token")
    return uuid.UUID(payload["sub"]), int(payload.get("tv", 0))
