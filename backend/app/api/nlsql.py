"""Natural-language record editing — propose, review the real diff, confirm.

Super Admin only. Every statement, whether written by the planner or typed by hand, goes
through the same guard, the same rolled-back preview, and the same per-row audit trail.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_principal
from app.config import settings
from app.db import get_db
from app.enums import Role
from app.models import ChangeRequest
from app.nlsql import SqlRejected, preview_sql
from app.nlsql.planner import NeedsClarification, PlannerUnavailable, plan
from app.nlsql.preview import ChangeConflict, ChangeTooLarge, apply_change, discard_change
from app.rbac import Principal
from app.schemas.common import Message, Page
from app.schemas.nlsql import ChangeApplied, ChangePreview, ProposeBody

router = APIRouter(prefix="/nlsql", tags=["nlsql"])


def require_super_admin(principal: Principal = Depends(get_principal)) -> Principal:
    """The blast radius of a generated statement is large enough that this is not routine.

    If merchandisers turn out to need it daily, that is a signal the console is missing a
    screen — not a reason to widen this.
    """
    if principal.role != Role.INTERNAL_SUPER_ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Natural-language record editing is restricted to Super Admins.",
        )
    return principal


@router.post("/propose", response_model=ChangePreview)
def propose(
    body: ProposeBody,
    principal: Principal = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> ChangePreview:
    """Generate the change, run it in a transaction, capture the real diff, roll back.

    Returns what *would* change, with before/after values per column. Nothing is committed
    until POST /nlsql/{id}/confirm.
    """
    sql = body.sql
    backend = "manual"
    model = None
    explanation = None

    if sql is None:
        try:
            planned, model = plan(db, body.prompt)
        except PlannerUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
        except NeedsClarification as exc:
            # 422 rather than 400: the request is well-formed, it is the intent that is
            # underspecified, and the client should render the question rather than an error.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"needs_clarification": True, "question": str(exc)},
            )
        sql = planned.sql
        explanation = planned.explanation
        backend = settings.nlsql_backend

    try:
        result = preview_sql(
            db,
            prompt=body.prompt,
            sql=sql,
            actor=principal,
            planner_backend=backend,
            planner_model=model,
            explanation=explanation,
            max_rows=body.max_rows or settings.nlsql_max_rows,
        )
    except SqlRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ChangeTooLarge as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - a bad generated statement is a 400, not a 500
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"That statement could not be run: {type(exc).__name__}: {exc}",
        )

    return ChangePreview.model_validate(result.change_request)


@router.get("/{change_id}", response_model=ChangePreview)
def get_change(
    change_id: uuid.UUID,
    principal: Principal = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> ChangePreview:
    change = db.get(ChangeRequest, change_id)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return ChangePreview.model_validate(change)


@router.post("/{change_id}/confirm", response_model=ChangeApplied)
def confirm(
    change_id: uuid.UUID,
    principal: Principal = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> ChangeApplied:
    """Commit a previewed change, if the targeted rows still look as they did."""
    change = db.get(ChangeRequest, change_id)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    try:
        applied = apply_change(db, change, principal)
    except ChangeConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    except SqlRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return ChangeApplied.model_validate(applied)


@router.post("/{change_id}/discard", response_model=Message)
def discard(
    change_id: uuid.UUID,
    reason: str | None = Query(None, max_length=500),
    principal: Principal = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> Message:
    change = db.get(ChangeRequest, change_id)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        discard_change(db, change, reason)
    except ChangeConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return Message(detail="Discarded")


@router.get("", response_model=Page[ChangePreview])
def list_changes(
    change_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> Page[ChangePreview]:
    """History of proposed and applied edits — including the ones that were discarded."""
    from sqlalchemy import func

    stmt = select(ChangeRequest)
    if change_status:
        stmt = stmt.where(ChangeRequest.status == change_status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(ChangeRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[ChangePreview](
        items=[ChangePreview.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )
