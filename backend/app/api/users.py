"""The Team page: requests waiting for approval, and everyone who has access. Admins only.

The endpoints are thin on purpose — every rule about who may move to which state, and every
guard (no acting on yourself, never lose the last admin), is in app/services/access.py.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from app.auth.deps import require_admin
from app.db import get_db
from app.enums import UserStatus
from app.models import User
from app.schemas import ApproveBody, RoleBody, TeamMember
from app.services import access, mailer

router = APIRouter(prefix="/users", tags=["users"])

# Pending first — that is what an admin opens this page to deal with.
_ORDER = case(
    (User.status == UserStatus.PENDING, 0),
    (User.status == UserStatus.ACTIVE, 1),
    (User.status == UserStatus.DISABLED, 2),
    else_=3,
)


def _row(user: User, reviewer_name: str | None) -> TeamMember:
    return TeamMember(
        id=user.id, name=user.name, email=user.email, role=user.role, status=user.status,
        avatar_url=user.avatar_url, has_password=user.has_password,
        google_linked=user.google_sub is not None, created_at=user.created_at, last_login_at=user.last_login_at,
        reviewed_at=user.reviewed_at, reviewed_by_name=reviewer_name,
    )


@router.get("", response_model=list[TeamMember])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    reviewer = aliased(User)
    rows = db.execute(
        select(User, reviewer.name)
        .outerjoin(reviewer, reviewer.id == User.reviewed_by_id)
        .order_by(_ORDER, User.created_at.desc())
    ).all()
    return [_row(u, name) for u, name in rows]


@router.get("/pending-count")
def pending_count(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    count = db.scalar(select(func.count()).select_from(User)
                      .where(User.status == UserStatus.PENDING)) or 0
    return {"count": count}


def _target(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such person")
    return user


def _apply(db: Session, target: User, change) -> TeamMember:
    try:
        change()
    except access.AccessError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, detail=exc.detail)
    db.commit()
    reviewer = db.get(User, target.reviewed_by_id) if target.reviewed_by_id else None
    return _row(target, reviewer.name if reviewer else None)


@router.post("/{user_id}/approve", response_model=TeamMember)
def approve(user_id: uuid.UUID, body: ApproveBody, background: BackgroundTasks,
            db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    target = _target(db, user_id)
    row = _apply(db, target, lambda: access.approve(db, target, admin, body.role))
    background.add_task(mailer.send, access.approved_notice(target))
    return row


@router.post("/{user_id}/reject", response_model=TeamMember)
def reject(user_id: uuid.UUID, db: Session = Depends(get_db),
           admin: User = Depends(require_admin)):
    target = _target(db, user_id)
    return _apply(db, target, lambda: access.reject(db, target, admin))


@router.post("/{user_id}/disable", response_model=TeamMember)
def disable(user_id: uuid.UUID, db: Session = Depends(get_db),
            admin: User = Depends(require_admin)):
    target = _target(db, user_id)
    return _apply(db, target, lambda: access.disable(db, target, admin))


@router.post("/{user_id}/restore", response_model=TeamMember)
def restore(user_id: uuid.UUID, db: Session = Depends(get_db),
            admin: User = Depends(require_admin)):
    target = _target(db, user_id)
    return _apply(db, target, lambda: access.restore(db, target, admin))


@router.put("/{user_id}/role", response_model=TeamMember)
def change_role(user_id: uuid.UUID, body: RoleBody, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    target = _target(db, user_id)
    return _apply(db, target, lambda: access.change_role(db, target, admin, body.role))
