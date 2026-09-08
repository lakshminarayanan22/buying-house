"""Who is calling. Every user here is Ecolink staff, so this is short by design."""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import TokenError, verify_session_token
from app.db import get_db
from app.enums import UserRole
from app.models import User


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        user_id, token_version = verify_session_token(authorization.split(" ", 1)[1].strip())
    except TokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    user = db.get(User, user_id)
    if user is None or not user.is_active or token_version != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    """Master data and user management. Everything else is open to both roles — with three
    people in the company, a finer permission model would be theatre."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admins only")
    return user
