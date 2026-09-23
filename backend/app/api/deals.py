"""Deals — the orchestration, its parties, and its follow-up list."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.deps import current_user
from app.db import get_db
from app.enums import ActivityAction, DealRole, DealStatus, ReferenceDomain as D
from app.models import Company, Deal, DealMilestone, DealParty, Document, ReferenceItem, User
from app.schemas import (
    DealDetail,
    DealIn,
    DealRow,
    DocOut,
    MilestoneIn,
    MilestoneOut,
    Msg,
    PartyIn,
    PartyOut,
)
from app.seed.taxonomy import resolve
from app.services import deals as svc

router = APIRouter(prefix="/deals", tags=["deals"])

def _ref(db: Session, domain: D, text: str | None, label: str) -> ReferenceItem | None:
    if not text:
        return None
    item = resolve(db, domain, text)
    if item is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"'{text}' is not a known {label}")
    return item


def _get(db: Session, deal_id: uuid.UUID) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return deal


def _row(db: Session, deal: Deal) -> DealRow:
    # Deal value is what the BUYER pays, not the sum of every leg. Summing a chain
    # double-counts: a 444k cotton trade has a 444k supplier leg and a 444k buyer leg, and
    # reporting 888k would overstate the book by the length of the chain.
    commission, count = db.execute(
        select(func.coalesce(func.sum(DealParty.commission_amount), 0),
               func.count(DealParty.id))
        .where(DealParty.deal_id == deal.id)
    ).one()
    value = db.scalar(
        select(func.coalesce(func.sum(DealParty.value), 0))
        .where(DealParty.deal_id == deal.id, DealParty.role == DealRole.BUYER)
    ) or 0
    if not value:
        # No buyer leg recorded yet — fall back to what the sell side is worth.
        value = db.scalar(
            select(func.coalesce(func.sum(DealParty.value), 0))
            .where(DealParty.deal_id == deal.id, DealParty.role != DealRole.BUYER)
        ) or 0
    names = list(db.scalars(
        select(Company.name).join(DealParty, DealParty.company_id == Company.id)
        .where(DealParty.deal_id == deal.id).order_by(DealParty.sequence)
    ).all())
    return DealRow(
        id=deal.id, deal_no=deal.deal_no, title=deal.title, status=deal.status,
        target_ship_date=deal.target_ship_date, last_activity_at=deal.last_activity_at,
        value=float(value), commission=float(commission), party_count=count,
        counterparties=names,
    )


@router.get("", response_model=list[DealRow])
def list_deals(
    search: str | None = Query(None, max_length=160),
    deal_status: DealStatus | None = None,
    open_only: bool = False,
    company_id: uuid.UUID | None = None,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[DealRow]:
    stmt = select(Deal)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(Deal.title).like(pattern),
                              func.lower(Deal.deal_no).like(pattern)))
    if deal_status:
        stmt = stmt.where(Deal.status == deal_status)
    if open_only:
        stmt = stmt.where(Deal.status.in_([s for s in DealStatus if s.is_open]))
    if company_id:
        stmt = stmt.where(
            select(DealParty.id).where(DealParty.deal_id == Deal.id,
                                       DealParty.company_id == company_id).exists()
        )
    rows = db.scalars(stmt.order_by(Deal.deal_no.desc())).all()
    return [_row(db, d) for d in rows]


def _detail(db: Session, deal: Deal) -> DealDetail:
    parties = db.scalars(
        select(DealParty).where(DealParty.deal_id == deal.id).order_by(DealParty.sequence)
    ).all()
    out_parties = []
    for p in parties:
        company = db.get(Company, p.company_id)
        process = db.get(ReferenceItem, p.process_id) if p.process_id else None
        out_parties.append(PartyOut(
            **PartyOut.model_validate(p).model_dump(
                exclude={"company_name", "process_name"}),
            company_name=company.name if company else None,
            process_name=process.name if process else None,
        ))

    milestones = db.scalars(
        select(DealMilestone).where(DealMilestone.deal_id == deal.id)
        .order_by(DealMilestone.planned_date, DealMilestone.sequence)
    ).all()
    documents = db.scalars(
        select(Document).where(Document.deal_id == deal.id).order_by(Document.created_at.desc())
    ).all()

    def name_of(ref_id):
        item = db.get(ReferenceItem, ref_id) if ref_id else None
        return item.name if item else None

    def code_of(ref_id):
        item = db.get(ReferenceItem, ref_id) if ref_id else None
        return item.code if item else None

    return DealDetail(
        **_row(db, deal).model_dump(),
        description=deal.description, notes=deal.notes, lost_reason=deal.lost_reason,
        product_name=name_of(deal.product_id), currency_code=code_of(deal.currency_id),
        incoterm_code=code_of(deal.incoterm_id),
        parties=out_parties,
        milestones=[
            MilestoneOut(**MilestoneOut.model_validate(ms).model_dump(exclude={"is_overdue"}),
                         is_overdue=ms.is_overdue)
            for ms in milestones
        ],
        documents=[DocOut.model_validate(d) for d in documents],
    )


@router.post("", response_model=DealDetail, status_code=201)
def create_deal(body: DealIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> DealDetail:
    deal = Deal(
        deal_no=svc.next_deal_no(db),
        **body.model_dump(exclude={"product_code", "currency_code", "incoterm_code"}),
        owner_user_id=user.id,
    )
    for code, domain, attr, label in [
        (body.product_code, D.PRODUCT, "product_id", "product"),
        (body.currency_code, D.CURRENCY, "currency_id", "currency"),
        (body.incoterm_code, D.INCOTERM, "incoterm_id", "incoterm"),
    ]:
        if code:
            setattr(deal, attr, _ref(db, domain, code, label).id)

    db.add(deal)
    db.flush()
    svc.touch(db, deal, actor_id=user.id, action=ActivityAction.CREATE,
              summary=f"Created {deal.deal_no} — {deal.title}")
    db.commit()
    db.refresh(deal)
    return _detail(db, deal)


@router.get("/{deal_id}", response_model=DealDetail)
def get_deal(deal_id: uuid.UUID, _: User = Depends(current_user),
             db: Session = Depends(get_db)) -> DealDetail:
    return _detail(db, _get(db, deal_id))


@router.patch("/{deal_id}", response_model=DealDetail)
def update_deal(deal_id: uuid.UUID, body: DealIn, user: User = Depends(current_user),
                db: Session = Depends(get_db)) -> DealDetail:
    deal = _get(db, deal_id)
    previous = deal.status
    payload = body.model_dump(exclude_unset=True,
                              exclude={"product_code", "currency_code", "incoterm_code"})
    for field, value in payload.items():
        setattr(deal, field, value)
    for code, domain, attr, label in [
        (body.product_code, D.PRODUCT, "product_id", "product"),
        (body.currency_code, D.CURRENCY, "currency_id", "currency"),
        (body.incoterm_code, D.INCOTERM, "incoterm_id", "incoterm"),
    ]:
        if code:
            setattr(deal, attr, _ref(db, domain, code, label).id)

    if deal.status == DealStatus.LOST and not deal.lost_reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="A lost deal needs a reason — it is the useful part.")
    if deal.status in {DealStatus.COMPLETED, DealStatus.LOST} and deal.closed_at is None:
        deal.closed_at = datetime.now(timezone.utc)

    summary = (f"Status {previous} -> {deal.status}" if previous != deal.status
               else "Updated deal")
    svc.touch(db, deal, actor_id=user.id,
              action=ActivityAction.STATUS_CHANGE if previous != deal.status
              else ActivityAction.UPDATE,
              summary=summary)
    db.commit()
    db.refresh(deal)
    return _detail(db, deal)


# --------------------------------------------------------------------- parties
@router.post("/{deal_id}/parties", response_model=DealDetail, status_code=201)
def add_party(deal_id: uuid.UUID, body: PartyIn, user: User = Depends(current_user),
              db: Session = Depends(get_db)) -> DealDetail:
    """Add a company to the chain. Its role here is what makes it a buyer or a supplier."""
    deal = _get(db, deal_id)
    if db.get(Company, body.company_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No such company")

    party = DealParty(
        deal_id=deal_id, **body.model_dump(exclude={"process_code"}),
    )
    if body.process_code:
        party.process_id = _ref(db, D.PROCESS, body.process_code, "process").id

    svc.refresh_commission(party)
    db.add(party)
    try:
        db.flush()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=_readable(exc))

    svc.touch(db, deal, actor_id=user.id, summary=f"Added a {body.role.lower()} to the chain")
    db.commit()
    db.refresh(deal)
    return _detail(db, deal)


@router.patch("/{deal_id}/parties/{party_id}", response_model=DealDetail)
def update_party(deal_id: uuid.UUID, party_id: uuid.UUID, body: PartyIn,
                 user: User = Depends(current_user), db: Session = Depends(get_db)) -> DealDetail:
    deal = _get(db, deal_id)
    party = db.get(DealParty, party_id)
    if party is None or party.deal_id != deal_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    payload = body.model_dump(exclude_unset=True, exclude={"process_code"})
    for field, value in payload.items():
        setattr(party, field, value)
    if body.process_code:
        party.process_id = _ref(db, D.PROCESS, body.process_code, "process").id

    # Only recompute when the caller did not state an amount, so a negotiated figure stands.
    svc.refresh_commission(party, overwrite="commission_amount" not in payload)
    try:
        db.flush()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=_readable(exc))

    svc.touch(db, deal, actor_id=user.id, summary="Updated a party on the chain")
    db.commit()
    db.refresh(deal)
    return _detail(db, deal)


@router.delete("/{deal_id}/parties/{party_id}", response_model=Msg)
def remove_party(deal_id: uuid.UUID, party_id: uuid.UUID, user: User = Depends(current_user),
                 db: Session = Depends(get_db)) -> Msg:
    deal = _get(db, deal_id)
    party = db.get(DealParty, party_id)
    if party is None or party.deal_id != deal_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(party)
    svc.touch(db, deal, actor_id=user.id, summary="Removed a party from the chain")
    db.commit()
    return Msg(detail="Removed")


# ------------------------------------------------------------------ milestones
@router.post("/{deal_id}/milestones", response_model=DealDetail, status_code=201)
def add_milestone(deal_id: uuid.UUID, body: MilestoneIn, user: User = Depends(current_user),
                  db: Session = Depends(get_db)) -> DealDetail:
    deal = _get(db, deal_id)
    milestone = DealMilestone(deal_id=deal_id, owner_user_id=user.id, **body.model_dump())
    db.add(milestone)
    try:
        db.flush()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=_readable(exc))

    svc.touch(db, deal, actor_id=user.id, summary=f"Added milestone: {body.name}")
    db.commit()
    db.refresh(deal)
    return _detail(db, deal)


@router.patch("/{deal_id}/milestones/{milestone_id}", response_model=DealDetail)
def update_milestone(deal_id: uuid.UUID, milestone_id: uuid.UUID, body: MilestoneIn,
                     user: User = Depends(current_user),
                     db: Session = Depends(get_db)) -> DealDetail:
    deal = _get(db, deal_id)
    milestone = db.get(DealMilestone, milestone_id)
    if milestone is None or milestone.deal_id != deal_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(milestone, field, value)
    # Ticking something off without saying when is the commonest way a follow-up list rots.
    if milestone.status == "DONE" and milestone.actual_date is None:
        from datetime import date as _date
        milestone.actual_date = _date.today()

    svc.touch(db, deal, actor_id=user.id, summary=f"{milestone.name}: {milestone.status}")
    db.commit()
    db.refresh(deal)
    return _detail(db, deal)


def _readable(exc: Exception) -> str:
    """Turn a constraint violation into something a merchandiser can act on."""
    text = str(getattr(exc, "orig", exc))
    for fragment, message in [
        ("margin_not_negative", "The resale price cannot be below what we pay."),
        ("percentage_needs_pct", "A percentage commission needs a percentage."),
        ("margin_needs_both_prices", "A margin needs both the cost and the resale price."),
        ("billed_needs_amount", "An invoiced commission needs an amount."),
        ("received_after_invoiced", "The received date cannot be before the invoice date."),
        ("uq_deal_party", "That company already has this role on the deal."),
        ("milestone_done_needs_date", "A completed milestone needs a date."),
    ]:
        if fragment in text:
            return message
    return "That change was rejected by the database."
