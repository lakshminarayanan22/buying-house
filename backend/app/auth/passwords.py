"""Argon2id password hashing, and the same primitive for OTP codes and invite tokens.

Invite tokens and OTP codes are stored hashed for the same reason passwords are: a database
dump must not be replayable as a login. Verification is constant-time via argon2's own
comparison.
"""
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


# OTP codes and invite/resume tokens use the same hashing; separate names keep call sites honest
# about what is being stored.
hash_secret = hash_password
verify_secret = verify_password
