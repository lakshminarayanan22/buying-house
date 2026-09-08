"""Deal mechanics and the three screens that get opened every day.

Those three questions — what is shipping this week, who owes us commission, which deals have
gone quiet — are the whole reporting surface. Each is a query; none needs a table of its own.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.enums import (
    ActivityAction,
    CommissionBasis,
    CommissionStatus,
    DealStatus,
    MilestoneStatus,
)
from app.models import ActivityLog, Company, Deal, DealMilestone, DealParty, ReferenceItem

_OPEN = [s for s in DealStatus if s.is_open]
_OWED = [CommissionStatus.DUE, CommissionStatus.INVOICED]


def next_deal_no(db: Session, on: date | None = None) -> str:
    """DL-2026-0007 — sequential within the year, so the number carries a date."""
    year = (on or date.today()).year
    prefix = f"DL-{year}-"
    highest = db.scalar(
        select(func.max(Deal.deal_no)).where(Deal.deal_no.like(f"{prefix}%"))
    )
    return f"{prefix}{(int(highest.rsplit('-', 1)[1]) + 1 if highest else 1):04d}"


def touch(db: Session, deal: Deal, *, actor_id: uuid.UUID | None = None,
          action: ActivityAction = ActivityAction.UPDATE, summary: str | None = None) -> None:
    """Record that something happened on a deal, and stamp it.

    Both halves matter: the log answers "who changed this", and the stamp is what the
    gone-quiet screen sorts on without scanning the log.
    """
    now = datetime.now(timezone.utc)
    deal.last_activity_at = now
    db.add(ActivityLog(
        entity_type="Deal", entity_id=deal.id, deal_id=deal.id,
        actor_user_id=actor_id, action=action, summary=summary,
    ))


def refresh_commission(party: DealParty, *, overwrite: bool = False) -> None:
    """Recompute what we earn on a leg, leaving a negotiated figure alone unless asked."""
    if party.commission_basis == CommissionBasis.FIXED:
        return                       # a fixed fee is typed, never derived
    computed = party.compute_commission()
    if computed is None:
        return
    if party.commission_amount is None or overwrite:
        party.commission_amount = computed


# ------------------------------------------------------------------ the three screens
def shipping_soon(db: Session, within_days: int = 7) -> list[dict]:
    """What leaves in the next week, plus anything already late."""
    horizon = date.today() + timedelta(days=within_days)
    rows = db.execute(
        select(
            DealParty.ship_date, Deal.deal_no, Deal.title, Company.name,
            ReferenceItem.name, DealParty.role, DealParty.value, DealParty.qty, DealParty.uom,
        )
        .join(Deal, Deal.id == DealParty.deal_id)
        .join(Company, Company.id == DealParty.company_id)
        .join(ReferenceItem, ReferenceItem.id == DealParty.process_id, isouter=True)
        .where(
            DealParty.ship_date.isnot(None),
            DealParty.ship_date <= horizon,
            Deal.status.in_(_OPEN),
        )
        .order_by(DealParty.ship_date)
    ).all()

    today = date.today()
    return [
        {"ship_date": d.isoformat(), "deal_no": no, "title": title, "company": company,
         "process": process, "role": role, "value": float(value or 0),
         "qty": float(qty) if qty is not None else None, "uom": uom,
         "days_out": (d - today).days, "overdue": d < today}
        for d, no, title, company, process, role, value, qty, uom in rows
    ]


def commission_owed(db: Session) -> dict:
    """Who owes us, and how much — the receivables view.

    Grouped by the company we bill, because chasing is a phone call to a company, not to a deal.
    """
    by_company = db.execute(
        select(
            Company.id, Company.name,
            func.count(DealParty.id),
            func.coalesce(func.sum(DealParty.commission_amount), 0),
            func.min(DealParty.invoiced_on),
        )
        .join(DealParty, DealParty.company_id == Company.id)
        .where(DealParty.commission_status.in_(_OWED))
        .group_by(Company.id, Company.name)
        .order_by(func.coalesce(func.sum(DealParty.commission_amount), 0).desc())
    ).all()

    totals = dict(db.execute(
        select(DealParty.commission_status,
               func.coalesce(func.sum(DealParty.commission_amount), 0))
        .group_by(DealParty.commission_status)
    ).all())

    today = date.today()
    return {
        "outstanding": float(sum(v for k, v in totals.items() if k in _OWED)),
        "received": float(totals.get(CommissionStatus.RECEIVED, 0)),
        "by_company": [
            {"company_id": str(cid), "company": name, "legs": legs, "amount": float(amount),
             "oldest_invoice": oldest.isoformat() if oldest else None,
             "days_outstanding": (today - oldest).days if oldest else None}
            for cid, name, legs, amount, oldest in by_company
        ],
    }


def gone_quiet(db: Session, silent_for_days: int = 14) -> list[dict]:
    """Open deals nobody has touched lately.

    Falls back to created_at where nothing has happened yet, so a deal entered three weeks ago
    and never followed up is exactly the kind that shows here.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=silent_for_days)
    last_touch = func.coalesce(Deal.last_activity_at, Deal.created_at)

    rows = db.execute(
        select(Deal.id, Deal.deal_no, Deal.title, Deal.status, last_touch, Deal.target_ship_date)
        .where(Deal.status.in_(_OPEN), last_touch < cutoff)
        .order_by(last_touch)
    ).all()

    now = datetime.now(timezone.utc)
    out = []
    for did, no, title, status, touched, ship in rows:
        if touched.tzinfo is None:
            touched = touched.replace(tzinfo=timezone.utc)
        out.append({
            "deal_id": str(did), "deal_no": no, "title": title, "status": status,
            "last_activity": touched.isoformat(),
            "days_silent": (now - touched).days,
            "target_ship_date": ship.isoformat() if ship else None,
        })
    return out


# ------------------------------------------------------------------------- extras
def open_milestones(db: Session, within_days: int = 14) -> list[dict]:
    """The follow-up list: what is due or already late across every open deal."""
    horizon = date.today() + timedelta(days=within_days)
    rows = db.execute(
        select(DealMilestone.planned_date, DealMilestone.name, DealMilestone.status,
               Deal.deal_no, Deal.title)
        .join(Deal, Deal.id == DealMilestone.deal_id)
        .where(
            Deal.status.in_(_OPEN),
            DealMilestone.status.notin_([MilestoneStatus.DONE, MilestoneStatus.SKIPPED]),
            or_(DealMilestone.planned_date.is_(None), DealMilestone.planned_date <= horizon),
        )
        .order_by(DealMilestone.planned_date)
    ).all()

    today = date.today()
    return [
        {"planned_date": d.isoformat() if d else None, "milestone": name, "status": status,
         "deal_no": no, "title": title,
         "overdue": bool(d and d < today)}
        for d, name, status, no, title in rows
    ]


def pipeline(db: Session) -> list[dict]:
    """Every deal by status, with the money attached."""
    rows = db.execute(
        select(Deal.status, func.count(func.distinct(Deal.id)),
               func.coalesce(func.sum(DealParty.value), 0),
               func.coalesce(func.sum(DealParty.commission_amount), 0))
        .join(DealParty, DealParty.deal_id == Deal.id, isouter=True)
        .group_by(Deal.status)
    ).all()
    return [
        {"status": s, "deals": n, "value": float(v), "commission": float(c)}
        for s, n, v, c in rows
    ]
