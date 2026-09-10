"""Signing in.

Two ways through the door, one account behind it:

- **Google** (`/auth/google`) is how an account comes to exist. Only @<allowed domain> Workspace
  accounts pass; a first sign-in creates the account in PENDING and tells the admins.
- **Password** (`/auth/login`) is a second way into an account that already exists and has been
  approved. Nobody can create an account with one, so it opens no door Google hasn't.

Both refuse anything but ACTIVE, and disabling someone on the Team page closes both at once.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import create_session_token, verify_password
from app.auth.deps import current_user
from app.auth.google import DomainNotAllowed, GoogleAuthError, enforce_domain, verify_credential
from app.config import settings
from app.db import get_db
from app.enums import UserStatus
from app.models import User
from app.schemas import (
    AuthConfig, GoogleSignInBody, LoginBody, Me, Msg, PasswordBody, Session as SessionOut,
    SignInResult,
)
from app.services import access, mailer

router = APIRouter(prefix="/auth", tags=["auth"])

STATUS_MESSAGES = {
    UserStatus.PENDING: "Your request has been sent to the Ecolink admins. You'll be able to "
                        "sign in as soon as one of them approves it — this only happens once.",
    UserStatus.REJECTED: "An admin declined this request. If that's a mistake, speak to them "
                         "directly and they can approve it from the Team page.",
    UserStatus.DISABLED: "Your access to Ecolink has been switched off. Speak to an admin if "
                         "you think this is wrong.",
}


def me_from(user: User) -> Me:
    return Me(id=user.id, name=user.name, email=user.email, role=user.role,
              avatar_url=user.avatar_url, has_password=user.has_password,
              google_linked=user.google_sub is not None)


@router.get("/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    return AuthConfig(
        google_backend=settings.google_auth_backend.lower(),
        google_client_id=settings.google_client_id,
        allowed_domain=settings.allowed_email_domain,
    )


@router.post("/google", response_model=SignInResult)
def google_sign_in(body: GoogleSignInBody, background: BackgroundTasks,
                   db: Session = Depends(get_db)) -> SignInResult:
    try:
        identity = verify_credential(body.credential)
        enforce_domain(identity)
    except GoogleAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except DomainNotAllowed as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))

    try:
        user, created = access.sign_in_with_google(db, identity)
    except access.AccessError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail)
    db.commit()

    if created and user.status == UserStatus.PENDING:
        background.add_task(mailer.send, access.request_notice(db, user))

    if user.status == UserStatus.ACTIVE:
        return SignInResult(
            status=user.status, name=user.name, email=user.email, message="Signed in",
            access_token=create_session_token(user.id, user.token_version),
        )
    return SignInResult(status=user.status, name=user.name, email=user.email,
                        message=STATUS_MESSAGES[user.status], newly_requested=created)


@router.post("/login", response_model=SessionOut)
def login(body: LoginBody, db: Session = Depends(get_db)) -> SessionOut:
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    # One message for every failure — wrong password, no such person, not approved — so the
    # form can't be used to find out who works here or who is waiting.
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access.record_login(db, user, "a password")
    db.commit()
    return SessionOut(access_token=create_session_token(user.id, user.token_version))


@router.get("/me", response_model=Me)
def me(user: User = Depends(current_user)) -> Me:
    return me_from(user)


@router.post("/password", response_model=SessionOut)
def set_password(body: PasswordBody, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> SessionOut:
    try:
        access.set_password(db, user, body.current_password, body.new_password)
    except access.AccessError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail)
    db.commit()
    # Setting a password signs out every other session; this device gets a fresh token.
    return SessionOut(access_token=create_session_token(user.id, user.token_version))


@router.post("/logout", response_model=Msg)
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Msg:
    user.token_version += 1     # invalidates every outstanding session for this user
    db.commit()
    return Msg(detail="Signed out")
