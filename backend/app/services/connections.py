"""The commercial layer: creating connections and reporting on what they earn.

Four questions the tracker has to answer, each a query rather than a table:
what are we owed, where does each deal stand, which suppliers earn us most, and what ships next.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.enums import (
    ChainStageStatus,
    CommissionStatus,
    ConnectionStatus,
)
from app.models import (
    BrandSupplierReveal,
    Connection,
    ConnectionStage,
    Organization,
    ReferenceItem,
)

# A stage past this point means the brand knows who the supplier is.
_REVEALED_FROM = {
    ChainStageStatus.INTRODUCED, ChainStageStatus.SAMPLING, ChainStageStatus.QUOTED,
    ChainStageStatus.AWARDED, ChainStageStatus.IN_PRODUCTION, ChainStageStatus.SHIPPED,
    ChainStageStatus.COMPLETED,
}

_OPEN_STATUSES = {
    ConnectionStatus.SCOPING, ConnectionStatus.INTRODUCED, ConnectionStatus.SAMPLING,
    ConnectionStatus.QUOTED, ConnectionStatus.CONFIRMED, ConnectionStatus.IN_PRODUCTION,
    ConnectionStatus.SHIPPED,
}


def next_connection_no(db: Session, on: date | None = None) -> str:
    """CN-2026-0007. Sequential within the year, so the number says when it started."""
    year = (on or date.today()).year
    prefix = f"CN-{year}-"
    highest = db.scalar(
        select(func.max(Connection.connection_no)).where(
            Connection.connection_no.like(f"{prefix}%")
        )
    )
    nxt = int(highest.rsplit("-", 1)[1]) + 1 if highest else 1
    return f"{prefix}{nxt:04d}"


def ensure_reveal(db: Session, connection: Connection, stage: ConnectionStage) -> None:
    """Introducing a supplier on a deal *is* the identity reveal.

    Without this the two would drift: a merchandiser marks a stage INTRODUCED, tells the brand
    the factory's name on a call, and the access-control layer still says they have never met.
    """
    if ChainStageStatus(stage.status) not in _REVEALED_FROM:
        return

    existing = db.scalars(
        select(BrandSupplierReveal).where(
            BrandSupplierReveal.brand_org_id == connection.brand_org_id,
            BrandSupplierReveal.supplier_org_id == stage.supplier_org_id,
        )
    ).first()

    if existing is None:
        db.add(
            BrandSupplierReveal(
                brand_org_id=connection.brand_org_id,
                supplier_org_id=stage.supplier_org_id,
                brand_sees_supplier=True,
                reason=f"Introduced on {connection.connection_no} — {connection.title}",
            )
        )
    elif not existing.brand_sees_supplier:
        existing.brand_sees_supplier = True
        existing.revoked_at = None


def refresh_commission(stage: ConnectionStage, *, overwrite: bool = False) -> None:
    """Recompute the earned amount, leaving a hand-entered figure alone unless told otherwise."""
    computed = stage.compute_commission()
    if computed is None:
        return
    if stage.commission_amount is None or overwrite:
        stage.commission_amount = computed


def roll_up_status(connection: Connection) -> ConnectionStatus:
    """Derive the connection's status from its stages — the deal is only as far as its slowest
    live stage, which is what a merchandiser means by "where is this"."""
    live = [
        ChainStageStatus(s.status) for s in connection.stages
        if ChainStageStatus(s.status) != ChainStageStatus.DROPPED
    ]
    if not live:
        return ConnectionStatus(connection.status)

    order = [
        (ChainStageStatus.PROPOSED, ConnectionStatus.SCOPING),
        (ChainStageStatus.INTRODUCED, ConnectionStatus.INTRODUCED),
        (ChainStageStatus.SAMPLING, ConnectionStatus.SAMPLING),
        (ChainStageStatus.QUOTED, ConnectionStatus.QUOTED),
        (ChainStageStatus.AWARDED, ConnectionStatus.CONFIRMED),
        (ChainStageStatus.IN_PRODUCTION, ConnectionStatus.IN_PRODUCTION),
        (ChainStageStatus.SHIPPED, ConnectionStatus.SHIPPED),
        (ChainStageStatus.COMPLETED, ConnectionStatus.CLOSED),
    ]
    rank = {stage: i for i, (stage, _) in enumerate(order)}
    slowest = min(live, key=lambda s: rank.get(s, 0))
    return dict(order)[slowest]


# --------------------------------------------------------------------- tracker views
def commission_ledger(db: Session, months: int = 12) -> list[dict]:
    """What we are owed and what has landed, by month. The receivables view."""
    since = date.today().replace(day=1) - timedelta(days=31 * months)

    rows = db.execute(
        select(
            ConnectionStage.commission_status,
            func.count(ConnectionStage.id),
            func.coalesce(func.sum(ConnectionStage.commission_amount), 0),
        )
        .where(ConnectionStage.commission_status != CommissionStatus.NOT_DUE)
        .group_by(ConnectionStage.commission_status)
    ).all()

    outstanding = db.scalar(
        select(func.coalesce(func.sum(ConnectionStage.commission_amount), 0)).where(
            ConnectionStage.commission_status.in_(
                [CommissionStatus.PENDING, CommissionStatus.INVOICED]
            )
        )
    ) or 0

    received = db.scalar(
        select(func.coalesce(func.sum(ConnectionStage.commission_amount), 0)).where(
            ConnectionStage.commission_status == CommissionStatus.RECEIVED,
            ConnectionStage.received_on >= since,
        )
    ) or 0

    return [
        {"bucket": status, "stages": count, "amount": float(total)}
        for status, count, total in rows
    ] + [
        {"bucket": "OUTSTANDING", "stages": None, "amount": float(outstanding)},
        {"bucket": f"RECEIVED_LAST_{months}M", "stages": None, "amount": float(received)},
    ]


def pipeline(db: Session) -> list[dict]:
    """Every open deal by stage of progress, with the money attached."""
    rows = db.execute(
        select(
            Connection.status,
            func.count(func.distinct(Connection.id)),
            func.coalesce(func.sum(ConnectionStage.order_value), 0),
            func.coalesce(func.sum(ConnectionStage.commission_amount), 0),
        )
        .join(ConnectionStage, ConnectionStage.connection_id == Connection.id, isouter=True)
        .group_by(Connection.status)
    ).all()
    return [
        {"status": status, "connections": count,
         "order_value": float(value), "commission": float(commission)}
        for status, count, value, commission in rows
    ]


def supplier_earnings(db: Session, limit: int = 20) -> list[dict]:
    """Which supplier relationships are actually worth the effort."""
    rows = db.execute(
        select(
            Organization.id,
            Organization.legal_name,
            func.count(func.distinct(ConnectionStage.connection_id)),
            func.coalesce(func.sum(ConnectionStage.order_value), 0),
            func.coalesce(func.sum(ConnectionStage.commission_amount), 0),
        )
        .join(ConnectionStage, ConnectionStage.supplier_org_id == Organization.id)
        .where(ConnectionStage.status != ChainStageStatus.DROPPED)
        .group_by(Organization.id, Organization.legal_name)
        .order_by(func.coalesce(func.sum(ConnectionStage.commission_amount), 0).desc())
        .limit(limit)
    ).all()
    return [
        {"supplier_org_id": str(oid), "supplier": name, "connections": count,
         "order_value": float(value), "commission": float(commission)}
        for oid, name, count, value, commission in rows
    ]


def upcoming_shipments(db: Session, within_days: int = 45) -> list[dict]:
    """What leaves the factory next, so we chase before the brand does."""
    horizon = date.today() + timedelta(days=within_days)

    rows = db.execute(
        select(
            ConnectionStage.ship_date, Connection.connection_no, Connection.title,
            Organization.legal_name, ReferenceItem.name, ConnectionStage.status,
            ConnectionStage.order_value,
        )
        .join(Connection, Connection.id == ConnectionStage.connection_id)
        .join(Organization, Organization.id == ConnectionStage.supplier_org_id)
        .join(ReferenceItem, ReferenceItem.id == ConnectionStage.process_type_id)
        .where(
            ConnectionStage.ship_date.isnot(None),
            ConnectionStage.ship_date <= horizon,
            ConnectionStage.status.notin_(
                [ChainStageStatus.COMPLETED, ChainStageStatus.DROPPED]
            ),
        )
        .order_by(ConnectionStage.ship_date)
    ).all()

    today = date.today()
    return [
        {"ship_date": ship.isoformat(), "connection_no": no, "title": title,
         "supplier": supplier, "stage": process, "status": status,
         "order_value": float(value or 0), "days_out": (ship - today).days,
         "overdue": ship < today}
        for ship, no, title, supplier, process, status, value in rows
    ]
