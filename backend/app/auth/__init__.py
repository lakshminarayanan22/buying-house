"""Authentication: password hashing, OTP, JWT tokens, and the FastAPI principal dependency."""
from app.auth.passwords import hash_password, hash_secret, verify_password, verify_secret
from app.auth.tokens import (
    TokenError,
    TokenExpiredError,
    create_invite_token,
    create_resume_token,
    create_session_token,
    verify_invite_token,
    verify_resume_token,
    verify_session_token,
)

__all__ = [
    "TokenError",
    "TokenExpiredError",
    "create_invite_token",
    "create_resume_token",
    "create_session_token",
    "hash_password",
    "hash_secret",
    "verify_invite_token",
    "verify_password",
    "verify_resume_token",
    "verify_secret",
    "verify_session_token",
]
