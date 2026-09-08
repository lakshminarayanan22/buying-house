from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, require_admin
from app.db import get_db
from app.enums import ReferenceDomain
from app.models import ReferenceItem, User
from app.schemas import RefOut

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


@router.get("", response_model=list[RefOut])
def list_items(
    domain: ReferenceDomain,
    search: str | None = Query(None, max_length=120),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[RefOut]:
    rows = db.scalars(
        select(ReferenceItem)
        .where(ReferenceItem.domain == domain, ReferenceItem.is_active.is_(True))
        .order_by(ReferenceItem.sort_order, ReferenceItem.name)
    ).all()

    if search:
        needle = search.lower()
        # Aliases are searched too, so "sinker" finds knitting and "cooling tech" finds
        # chemical supply — the words people actually type.
        rows = [
            r for r in rows
            if needle in r.name.lower() or needle in r.code.lower()
            or any(needle in a.lower() for a in (r.aliases or []))
        ]
    return [RefOut.model_validate(r) for r in rows]


@router.post("", response_model=RefOut, status_code=201)
def create_item(
    body: RefOut,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RefOut:
    clash = db.scalars(
        select(ReferenceItem).where(
            ReferenceItem.domain == body.domain, ReferenceItem.code == body.code
        )
    ).first()
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That code already exists")

    item = ReferenceItem(domain=body.domain, code=body.code, name=body.name,
                         aliases=body.aliases or [], parent_id=body.parent_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return RefOut.model_validate(item)
