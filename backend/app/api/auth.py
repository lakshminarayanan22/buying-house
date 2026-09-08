from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import create_session_token, verify_password
from app.auth.deps import current_user
from app.db import get_db
from app.enums import ActivityAction
from app.models import ActivityLog, User
from app.schemas import LoginBody, Me, Msg, Session as SessionOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionOut)
def login(body: LoginBody, db: Session = Depends(get_db)) -> SessionOut:
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    # One message for every failure, so the form cannot be used to find out who works here.
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user.last_login_at = datetime.now(timezone.utc)
    db.add(ActivityLog(entity_type="User", entity_id=user.id, actor_user_id=user.id,
                       action=ActivityAction.LOGIN, actor_label=user.name, summary="Signed in"))
    db.commit()
    return SessionOut(access_token=create_session_token(user.id, user.token_version))


@router.get("/me", response_model=Me)
def me(user: User = Depends(current_user)) -> Me:
    return Me.model_validate(user)


@router.post("/logout", response_model=Msg)
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Msg:
    user.token_version += 1     # invalidates every outstanding session for this user
    db.commit()
    return Msg(detail="Signed out")
