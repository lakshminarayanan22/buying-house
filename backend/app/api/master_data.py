"""Taxonomy CRUD and the unmapped-term review queue (§3, §12 step 3)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.deps import get_principal
from app.db import get_db
from app.enums import ActivityAction, ReferenceDomain
from app.models import ReferenceAlias, ReferenceItem, UnmappedTerm
from app.rbac import Action, Principal, require
from app.schemas.common import Message, Page
from app.schemas.reference import (
    AliasCreate,
    ReferenceItemCreate,
    ReferenceItemOut,
    ReferenceItemUpdate,
    ReferenceItemWithAliases,
    ResolveUnmappedBody,
    UnmappedTermOut,
)
from app.services import activity
from app.services.taxonomy import add_alias, refresh_path, resolve_unmapped

router = APIRouter(prefix="/master-data", tags=["master-data"])


def _with_aliases(item: ReferenceItem) -> ReferenceItemWithAliases:
    return ReferenceItemWithAliases(
        **ReferenceItemOut.model_validate(item).model_dump(),
        aliases=[a.alias for a in item.aliases],
    )


@router.get("/domains", response_model=list[str])
def list_domains(_: Principal = Depends(get_principal)) -> list[str]:
    return [d.value for d in ReferenceDomain]


@router.get("/items", response_model=list[ReferenceItemWithAliases])
def list_items(
    domain: ReferenceDomain,
    search: str | None = Query(None, max_length=120),
    include_inactive: bool = False,
    parent_id: uuid.UUID | None = None,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[ReferenceItemWithAliases]:
    """The taxonomy is readable by every authenticated user — a supplier has to fill a form."""
    require(principal, Action.VIEW, "ReferenceItem")

    stmt = (
        select(ReferenceItem)
        .options(selectinload(ReferenceItem.aliases))
        .where(ReferenceItem.domain == domain)
        .order_by(ReferenceItem.path, ReferenceItem.sort_order, ReferenceItem.name)
    )
    if not include_inactive:
        stmt = stmt.where(ReferenceItem.is_active.is_(True))
    if parent_id is not None:
        stmt = stmt.where(ReferenceItem.parent_id == parent_id)
    if search:
        pattern = f"%{search.lower()}%"
        # Search aliases too: someone typing "sinker" into the picker should find Single Jersey.
        alias_hits = select(ReferenceAlias.item_id).where(ReferenceAlias.normalised.like(pattern))
        stmt = stmt.where(
            func.lower(ReferenceItem.name).like(pattern)
            | func.lower(ReferenceItem.code).like(pattern)
            | ReferenceItem.id.in_(alias_hits)
        )

    return [_with_aliases(item) for item in db.scalars(stmt).all()]


@router.post("/items", response_model=ReferenceItemWithAliases, status_code=201)
def create_item(
    body: ReferenceItemCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ReferenceItemWithAliases:
    require(principal, Action.MANAGE_MASTER_DATA, "ReferenceItem")

    existing = db.scalars(
        select(ReferenceItem).where(
            ReferenceItem.domain == body.domain, ReferenceItem.code == body.code
        )
    ).first()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="That code already exists")

    if body.parent_id is not None:
        parent = db.get(ReferenceItem, body.parent_id)
        if parent is None or parent.domain != body.domain:
            # A category cannot have a fibre as its parent.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Parent must be in the same domain"
            )

    item = ReferenceItem(
        domain=body.domain, code=body.code, name=body.name, description=body.description,
        parent_id=body.parent_id, sort_order=body.sort_order,
    )
    db.add(item)
    db.flush()
    refresh_path(db, item)
    for alias in body.aliases:
        add_alias(db, item, alias)

    activity.record(
        db, entity_type="ReferenceItem", entity_id=item.id, action=ActivityAction.CREATE,
        actor=principal, summary=f"Created {body.domain}:{body.code}",
    )
    db.commit()
    db.refresh(item)
    return _with_aliases(item)


@router.patch("/items/{item_id}", response_model=ReferenceItemWithAliases)
def update_item(
    item_id: uuid.UUID,
    body: ReferenceItemUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ReferenceItemWithAliases:
    require(principal, Action.MANAGE_MASTER_DATA, "ReferenceItem")

    item = db.get(ReferenceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    reparented = False
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "parent_id" and value != item.parent_id:
            reparented = True
        setattr(item, field, value)

    activity.record_changes(db, item, actor=principal, summary="Updated taxonomy value")
    if reparented:
        refresh_path(db, item)

    db.commit()
    db.refresh(item)
    return _with_aliases(item)


@router.post("/items/{item_id}/aliases", response_model=Message, status_code=201)
def create_alias(
    item_id: uuid.UUID,
    body: AliasCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Message:
    """Teach the taxonomy a synonym — the highest-leverage thing an admin does here."""
    require(principal, Action.MANAGE_MASTER_DATA, "ReferenceItem")

    item = db.get(ReferenceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    add_alias(db, item, body.alias, body.language)
    db.commit()
    return Message(detail=f"'{body.alias}' now resolves to {item.code}")


# --------------------------------------------------------------------- review queue
@router.get("/unmapped", response_model=Page[UnmappedTermOut])
def list_unmapped(
    domain: ReferenceDomain | None = None,
    resolved: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[UnmappedTermOut]:
    """Terms users typed that the taxonomy did not recognise, most frequent first.

    §11's "other" escape hatch, as a ranked to-do list rather than a free-text graveyard.
    """
    require(principal, Action.VIEW_INTERNAL, "UnmappedTerm")

    stmt = select(UnmappedTerm)
    if domain is not None:
        stmt = stmt.where(UnmappedTerm.domain == domain)
    stmt = stmt.where(
        UnmappedTerm.resolved_item_id.isnot(None) if resolved
        else UnmappedTerm.resolved_item_id.is_(None)
    )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(UnmappedTerm.occurrences.desc(), UnmappedTerm.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return Page[UnmappedTermOut](
        items=[UnmappedTermOut.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("/unmapped/{term_id}/resolve", response_model=ReferenceItemWithAliases)
def resolve_term(
    term_id: uuid.UUID,
    body: ResolveUnmappedBody,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ReferenceItemWithAliases:
    """Map a queued term onto an existing value, or promote it into a new one.

    Either way the raw text becomes a permanent alias, so the same phrasing resolves silently
    the next time — the queue teaches the taxonomy rather than just clearing itself.
    """
    require(principal, Action.MANAGE_MASTER_DATA, "ReferenceItem")

    term = db.get(UnmappedTerm, term_id)
    if term is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    if body.item_id is not None:
        item = db.get(ReferenceItem, body.item_id)
        if item is None or item.domain != term.domain:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Target must be in the same domain"
            )
    elif body.new_code and body.new_name:
        item = ReferenceItem(
            domain=term.domain, code=body.new_code, name=body.new_name, parent_id=body.parent_id
        )
        db.add(item)
        db.flush()
        refresh_path(db, item)
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Provide either item_id, or new_code and new_name",
        )

    resolve_unmapped(db, term, item, principal.user_id)
    activity.record(
        db, entity_type="UnmappedTerm", entity_id=term.id, action=ActivityAction.UPDATE,
        actor=principal, summary=f"Mapped '{term.raw_text}' to {item.code}",
    )
    db.commit()
    db.refresh(item)
    return _with_aliases(item)
