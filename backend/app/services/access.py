"""Who gets in, and every way that can change.

Signing in with Google proves who someone is. It does not let them in: a new account starts
PENDING and an admin approves it, once. After that the person goes straight through on every
sign-in until an admin switches them off.

All of it lives here so the rules are written down once:

    PENDING  --approve-->  ACTIVE  --disable-->  DISABLED
       |                     ^                      |
       +---reject--> REJECTED +------approve--------+ (restore)

Two guards sit over every change. An admin cannot act on their own access — it is too easy to
lock yourself out, and "I approved my own promotion" is not a sentence an audit trail should
contain. And the last active admin can never be disabled or demoted, because then nobody could
approve anyone again without a database console.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.auth.google import GoogleIdentity
from app.config import settings
from app.enums import ActivityAction, UserRole, UserStatus
from app.models import ActivityLog, User
from app.services.mailer import Email


class AccessError(Exception):
    """A request the rules refuse. Carries the HTTP status the API should answer with."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log(db: Session, action: ActivityAction, target: User, actor: User | None,
         summary: str, before: dict | None = None, after: dict | None = None) -> None:
    db.add(ActivityLog(
        entity_type="User", entity_id=target.id, action=action, summary=summary,
        actor_user_id=actor.id if actor else None,
        actor_label=actor.name if actor else "system",
        before=before, after=after,
    ))


# ----------------------------------------------------------------------------- sign-in
def sign_in_with_google(db: Session, identity: GoogleIdentity) -> tuple[User, bool]:
    """Find or create the account for a Google identity that has already passed the domain
    check. Returns (user, created). The caller decides what the user's status lets them do."""
    user = db.scalars(select(User).where(User.google_sub == identity.sub)).first()

    if user is None:
        user = db.scalars(
            select(User).where(func.lower(User.email) == identity.email)
        ).first()
        if user is not None and user.google_sub and user.google_sub != identity.sub:
            # Same address, different Google account. Workspace can recycle an address after
            # someone leaves; that must never inherit the previous person's access.
            raise AccessError(
                "This address is linked to a different Google account. Ask an admin.", 403
            )
        if user is not None:
            user.google_sub = identity.sub      # an existing password account, now linked

    created = user is None
    if created:
        user = User(email=identity.email, name=identity.name, google_sub=identity.sub,
                    avatar_url=identity.picture, status=UserStatus.PENDING,
                    role=UserRole.MEMBER)
        db.add(user)
        db.flush()
        _log(db, ActivityAction.ACCESS_REQUESTED, user, user, f"{user.name} asked for access")
    else:
        user.name = identity.name or user.name
        user.avatar_url = identity.picture
        # Matched on sub, so if Workspace renamed the address, follow it — unless another row
        # already holds the new one, which would mean two people and needs a human.
        if user.email.lower() != identity.email:
            clash = db.scalars(
                select(User).where(func.lower(User.email) == identity.email, User.id != user.id)
            ).first()
            if clash is None:
                user.email = identity.email

    # Configured admins are let in by configuration — how the very first request is ever
    # approved. Only from PENDING: someone an admin has deliberately switched off stays off,
    # config or no config.
    if user.status == UserStatus.PENDING and identity.email in settings.bootstrap_admins:
        user.status = UserStatus.ACTIVE
        user.role = UserRole.ADMIN
        user.reviewed_at = _now()
        _log(db, ActivityAction.ACCESS_APPROVED, user, None,
             f"{user.name} approved as Admin by configuration (BOOTSTRAP_ADMIN_EMAILS)")

    if user.status == UserStatus.ACTIVE:
        record_login(db, user, "Google")

    return user, created


def record_login(db: Session, user: User, method: str) -> None:
    user.last_login_at = _now()
    _log(db, ActivityAction.LOGIN, user, user, f"Signed in with {method}")


# ------------------------------------------------------------------------ transitions
def _active_admin_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(
        User.role == UserRole.ADMIN, User.status == UserStatus.ACTIVE)) or 0


def _not_self(target: User, actor: User, verb: str) -> None:
    if target.id == actor.id:
        raise AccessError(f"You can't {verb} your own account. Ask another admin.", 403)


def _not_last_admin(db: Session, target: User, verb: str) -> None:
    if (target.role == UserRole.ADMIN and target.status == UserStatus.ACTIVE
            and _active_admin_count(db) <= 1):
        raise AccessError(
            f"Can't {verb} the only active admin — nobody would be left to approve anyone. "
            "Make someone else an admin first."
        )


def approve(db: Session, target: User, actor: User, role: UserRole) -> None:
    if target.status not in (UserStatus.PENDING, UserStatus.REJECTED):
        raise AccessError(f"{target.name} isn't waiting for approval.")
    before = {"status": target.status, "role": target.role}
    target.status, target.role = UserStatus.ACTIVE, role
    target.reviewed_at, target.reviewed_by_id = _now(), actor.id
    _log(db, ActivityAction.ACCESS_APPROVED, target, actor,
         f"{actor.name} approved {target.name} as {role.value.title()}",
         before=before, after={"status": UserStatus.ACTIVE, "role": role})


def reject(db: Session, target: User, actor: User) -> None:
    if target.status != UserStatus.PENDING:
        raise AccessError(f"{target.name} isn't waiting for approval.")
    target.status = UserStatus.REJECTED
    target.reviewed_at, target.reviewed_by_id = _now(), actor.id
    _log(db, ActivityAction.ACCESS_REJECTED, target, actor,
         f"{actor.name} declined {target.name}'s request")


def disable(db: Session, target: User, actor: User) -> None:
    _not_self(target, actor, "disable")
    if target.status != UserStatus.ACTIVE:
        raise AccessError(f"{target.name} doesn't currently have access.")
    _not_last_admin(db, target, "disable")
    target.status = UserStatus.DISABLED
    target.token_version += 1           # every open session, on every device, ends now
    target.reviewed_at, target.reviewed_by_id = _now(), actor.id
    _log(db, ActivityAction.ACCESS_DISABLED, target, actor,
         f"{actor.name} switched off {target.name}'s access")


def restore(db: Session, target: User, actor: User) -> None:
    if target.status != UserStatus.DISABLED:
        raise AccessError(f"{target.name}'s access isn't switched off.")
    target.status = UserStatus.ACTIVE
    target.reviewed_at, target.reviewed_by_id = _now(), actor.id
    _log(db, ActivityAction.ACCESS_RESTORED, target, actor,
         f"{actor.name} restored {target.name}'s access")


def change_role(db: Session, target: User, actor: User, role: UserRole) -> None:
    _not_self(target, actor, "change the role of")
    if target.role == role:
        return
    if role != UserRole.ADMIN:
        _not_last_admin(db, target, "demote")
    before = target.role
    target.role = role
    _log(db, ActivityAction.ROLE_CHANGE, target, actor,
         f"{actor.name} made {target.name} {role.value.title()}",
         before={"role": before}, after={"role": role})


# --------------------------------------------------------------------------- password
def set_password(db: Session, user: User, current: str | None, new: str) -> None:
    """Add or change the optional password on an approved account.

    Changing one needs the current one, so a session left open on someone else's laptop can't
    be used to take the account over permanently. Adding the first one doesn't — the person
    has just proven who they are through Google to be here at all.
    """
    if not user.is_active:
        raise AccessError("Only approved accounts can set a password.", 403)
    if len(new) < settings.password_min_length:
        raise AccessError(
            f"Use at least {settings.password_min_length} characters.", 422)
    if user.password_hash is not None and not verify_password(user.password_hash, current or ""):
        raise AccessError("Your current password is incorrect.", 403)

    had_one = user.password_hash is not None
    user.password_hash = hash_password(new)
    # Rotate sessions: anyone who knew the old password and signed in with it is signed out.
    # The caller issues a fresh token for the device making the change.
    user.token_version += 1
    _log(db, ActivityAction.PASSWORD_SET, user, user,
         "Changed their password" if had_one else "Added a password")


# ----------------------------------------------------------------------------- email
def request_notice(db: Session, requester: User) -> Email:
    admins = db.scalars(select(User.email).where(
        User.role == UserRole.ADMIN, User.status == UserStatus.ACTIVE)).all()
    return Email(
        to=tuple(admins),
        subject=f"{requester.name} is waiting for access to Ecolink",
        body=(
            f"{requester.name} <{requester.email}> signed in with Google and is waiting for "
            "approval.\n\n"
            f"Review the request: {settings.app_base_url}/team\n\n"
            "Approving is a one-time step — once approved, they sign straight in from then on."
        ),
    )


def approved_notice(user: User) -> Email:
    return Email(
        to=(user.email,),
        subject="You now have access to Ecolink",
        body=(
            f"Hi {user.name.split(' ')[0]},\n\n"
            f"Your access to Ecolink has been approved as {user.role.value.title()}.\n\n"
            f"Sign in with your Google account: {settings.app_base_url}/login\n"
        ),
    )
