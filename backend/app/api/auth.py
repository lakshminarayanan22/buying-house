"""Login, OTP, invite acceptance, and /me."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    TokenError,
    create_session_token,
    hash_password,
    hash_secret,
    verify_password,
)
from app.auth.deps import get_current_user, get_principal
from app.auth.otp import OtpError, issue_challenge, verify_code
from app.auth.tokens import verify_invite_token
from app.config import settings
from app.db import get_db
from app.enums import ActivityAction, NotificationChannel, OrgStatus, Role, UserStatus
from app.models import Organization, OrgInvite, User
from app.rbac import Principal
from app.schemas.auth import (
    AcceptInviteBody,
    CurrentUser,
    OtpRequestBody,
    OtpVerifyBody,
    PasswordLoginRequest,
    SessionResponse,
)
from app.schemas.common import Message
from app.services import activity
from app.services.notifications import EventKey, enqueue

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every credential failure. Distinguishing "no such user" from "wrong password"
# turns the login form into a directory of who we work with.
_INVALID = "Invalid credentials"


def _portals_for(role: Role) -> list[str]:
    return {"INTERNAL": ["internal"], "BRAND": ["brand"], "SUPPLIER": ["supplier"]}[
        role.side.value
    ]


def _issue_session(db: Session, user: User) -> SessionResponse:
    user.last_login_at = datetime.now(timezone.utc)
    activity.record(
        db, entity_type="User", entity_id=user.id, action=ActivityAction.LOGIN,
        org_id=user.org_id, actor_label=user.name, summary="Signed in",
    )
    db.commit()
    return SessionResponse(
        access_token=create_session_token(user.id, user.token_version),
        expires_in_hours=settings.session_token_ttl_hours,
    )


@router.post("/login", response_model=SessionResponse)
def login(body: PasswordLoginRequest, db: Session = Depends(get_db)) -> SessionResponse:
    """Password login — internal staff and brand users."""
    user = db.scalars(
        select(User).where(func.lower(User.email) == body.email.lower())
    ).first()

    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_INVALID)
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_INVALID)

    return _issue_session(db, user)


@router.post("/otp/request", response_model=Message)
def request_otp(body: OtpRequestBody, db: Session = Depends(get_db)) -> Message:
    """Send a login code — the path suppliers use (§5.2).

    Always returns the same response whether or not the number is registered, so this endpoint
    cannot be used to discover which factories we work with.
    """
    destination = (body.phone or body.email or "").strip()
    if not destination:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="phone or email is required")

    user = db.scalars(
        select(User).where((User.phone == destination) | (User.email == destination))
    ).first()

    if user is not None and user.status == UserStatus.ACTIVE:
        channel = NotificationChannel.WHATSAPP if body.phone else NotificationChannel.EMAIL
        _challenge, code = issue_challenge(db, destination, channel.value, user)
        enqueue(
            db,
            event_key=EventKey.OTP_CODE,
            user=user,
            channels=[channel],
            payload={
                "code": code,
                "app_name": "Buying House",
                "ttl_minutes": settings.otp_ttl_minutes,
            },
            address_override=destination,
        )
        db.commit()

    return Message(detail="If that number is registered, a code has been sent.")


@router.post("/otp/verify", response_model=SessionResponse)
def verify_otp(body: OtpVerifyBody, db: Session = Depends(get_db)) -> SessionResponse:
    destination = (body.phone or body.email or "").strip()
    if not destination:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="phone or email is required")

    try:
        user_id = verify_code(db, destination, body.code)
    except OtpError:
        db.commit()  # persist the attempt counter even on failure
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_INVALID)

    user = db.get(User, user_id) if user_id else None
    if user is None or user.status != UserStatus.ACTIVE:
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_INVALID)

    return _issue_session(db, user)


@router.post("/invite/accept", response_model=SessionResponse)
def accept_invite(body: AcceptInviteBody, db: Session = Depends(get_db)) -> SessionResponse:
    """Turn an invite token into an active user.

    org_id and role come from the signed token, never from the request body — that is what
    stops an invitee joining a different organization or granting themselves an admin role.
    """
    try:
        invite_id, org_id, role_value = verify_invite_token(body.token)
    except TokenError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invitation")

    invite = db.get(OrgInvite, invite_id)
    if invite is None or invite.org_id != org_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invitation")
    if invite.accepted_at is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="This invitation has been used")

    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invitation")

    role = Role(role_value)
    if role.is_internal:
        # Internal accounts are never created through a public endpoint.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid invitation")

    phone = body.phone or invite.phone
    if not invite.email and not phone:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="A phone number is required")

    user = User(
        org_id=org_id,
        role=role,
        name=body.name,
        email=invite.email,
        phone=phone,
        whatsapp=phone,
        password_hash=hash_password(body.password) if body.password else None,
        language_pref=body.language_pref,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()

    invite.accepted_at = datetime.now(timezone.utc)
    invite.accepted_by_user_id = user.id

    org = db.get(Organization, org_id)
    if org is not None:
        if org.owner_user_id is None:
            org.owner_user_id = user.id
        # First acceptance moves the shell out of INVITED so the onboarding wizard can start.
        if org.status == OrgStatus.INVITED:
            org.status = OrgStatus.DRAFT

    activity.record(
        db, entity_type="Organization", entity_id=org_id, action=ActivityAction.INVITE_ACCEPTED,
        org_id=org_id, actor_label=user.name, summary=f"{user.name} accepted the invitation",
    )
    db.commit()
    return _issue_session(db, user)


@router.get("/me", response_model=CurrentUser)
def me(
    user: User = Depends(get_current_user),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CurrentUser:
    org = db.get(Organization, user.org_id) if user.org_id else None
    return CurrentUser(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=Role(user.role),
        side=principal.side.value,
        org_id=user.org_id,
        org_name=org.display_name if org else None,
        org_status=org.status if org else None,
        language_pref=user.language_pref,
        portals=_portals_for(Role(user.role)),
    )


@router.post("/logout", response_model=Message)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Message:
    """Invalidate every outstanding session for this user by bumping token_version."""
    user.token_version += 1
    db.commit()
    return Message(detail="Signed out")
