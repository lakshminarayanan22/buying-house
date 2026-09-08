"""Deals — the business Ecolink actually does.

A deal is one piece of orchestration: Australian cotton into an Indian spinning mill; Japanese
cooling chemistry through a Tiruppur dye house and on to a brand. What varies between those is
only *who is involved and in what capacity*, so the parties are rows and the deal itself stays
thin.

Commission sits on the party, not on the deal, because it genuinely differs per leg — a
percentage of the cotton trade, a margin on the finished fabric — and one deal can carry both.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import (
    CommissionBasis,
    CommissionStatus,
    DealRole,
    DealStatus,
    MilestoneStatus,
)
from app.models.base import Base, TimestampMixin, uuid_pk


class Deal(Base, TimestampMixin):
    __tablename__ = "deal"

    id: Mapped[uuid.UUID] = uuid_pk()
    deal_no: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT"), index=True
    )
    currency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT")
    )
    incoterm_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT")
    )

    status: Mapped[DealStatus] = mapped_column(
        String(16), nullable=False, default=DealStatus.LEAD,
        server_default=DealStatus.LEAD.value, index=True,
    )
    lost_reason: Mapped[str | None] = mapped_column(String(400))

    target_ship_date: Mapped[date | None] = mapped_column(Date, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), index=True
    )

    # Touched on every meaningful change. "Which deals have gone quiet" is a sort on this
    # column, which beats scanning the activity log every time the screen loads.
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    notes: Mapped[str | None] = mapped_column(Text)

    parties: Mapped[list["DealParty"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan", order_by="DealParty.sequence"
    )
    milestones: Mapped[list["DealMilestone"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan",
        order_by="DealMilestone.sequence",
    )

    __table_args__ = (
        UniqueConstraint("deal_no", name="uq_deal_no"),
        CheckConstraint(
            "status <> 'LOST' OR lost_reason IS NOT NULL", name="deal_lost_needs_reason"
        ),
        Index("ix_deal_status_ship", "status", "target_ship_date"),
    )

    @property
    def commission_total(self) -> float:
        return float(sum(p.commission_amount or 0 for p in self.parties))

    @property
    def buyers(self) -> list["DealParty"]:
        return [p for p in self.parties if p.role == DealRole.BUYER]


class DealParty(Base, TimestampMixin):
    """One company's involvement in one deal, and what we earn from it.

    The same company can appear twice in a deal under different roles — a mill that buys our
    cotton and later processes fabric for the same programme — so the unique key includes role.
    """

    __tablename__ = "deal_party"

    id: Mapped[uuid.UUID] = uuid_pk()
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("deal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    role: Mapped[DealRole] = mapped_column(String(20), nullable=False, index=True)
    # What they do on this deal — spinning, dyeing, supplying chemistry. Optional: a buyer has
    # no process.
    process_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    uom: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[float | None] = mapped_column(Numeric(14, 4))
    value: Mapped[float | None] = mapped_column(Numeric(16, 2))

    # What we sell it on at, when the earning is a margin rather than a percentage.
    resale_unit_price: Mapped[float | None] = mapped_column(Numeric(14, 4))

    commission_basis: Mapped[CommissionBasis] = mapped_column(
        String(16), nullable=False, default=CommissionBasis.NONE,
        server_default=CommissionBasis.NONE.value,
    )
    commission_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    commission_amount: Mapped[float | None] = mapped_column(Numeric(16, 2))
    commission_status: Mapped[CommissionStatus] = mapped_column(
        String(16), nullable=False, default=CommissionStatus.NOT_DUE,
        server_default=CommissionStatus.NOT_DUE.value, index=True,
    )
    invoiced_on: Mapped[date | None] = mapped_column(Date)
    received_on: Mapped[date | None] = mapped_column(Date, index=True)

    ship_date: Mapped[date | None] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    deal: Mapped[Deal] = relationship(back_populates="parties")

    __table_args__ = (
        UniqueConstraint("deal_id", "company_id", "role", name="uq_deal_party"),
        CheckConstraint(
            "commission_basis <> 'PERCENTAGE' OR commission_pct IS NOT NULL",
            name="deal_party_percentage_needs_pct",
        ),
        CheckConstraint(
            "commission_basis <> 'MARGIN' "
            "OR (unit_price IS NOT NULL AND resale_unit_price IS NOT NULL)",
            name="deal_party_margin_needs_both_prices",
        ),
        CheckConstraint(
            "resale_unit_price IS NULL OR unit_price IS NULL "
            "OR resale_unit_price >= unit_price",
            name="deal_party_margin_not_negative",
        ),
        CheckConstraint(
            "commission_status NOT IN ('INVOICED','RECEIVED') OR commission_amount IS NOT NULL",
            name="deal_party_billed_needs_amount",
        ),
        CheckConstraint(
            "received_on IS NULL OR invoiced_on IS NULL OR received_on >= invoiced_on",
            name="deal_party_received_after_invoiced",
        ),
        Index("ix_deal_party_ledger", "commission_status", "received_on"),
    )

    def compute_commission(self) -> float | None:
        """What we earn on this leg, from the basis recorded on it."""
        if self.commission_basis == CommissionBasis.PERCENTAGE:
            if self.value is None or self.commission_pct is None:
                return None
            return round(float(self.value) * float(self.commission_pct) / 100, 2)
        if self.commission_basis == CommissionBasis.MARGIN:
            if self.resale_unit_price is None or self.unit_price is None or self.qty is None:
                return None
            return round(
                (float(self.resale_unit_price) - float(self.unit_price)) * float(self.qty), 2
            )
        if self.commission_basis == CommissionBasis.FIXED:
            return float(self.commission_amount) if self.commission_amount is not None else None
        return 0.0


class DealMilestone(Base, TimestampMixin):
    """The follow-up list for a deal.

    "We definitely need to keep track of these processes and follow up" — so this is a dated
    checklist per deal rather than a full time-and-action calendar. A milestone can be pinned to
    one party (dyeing complete) or belong to the deal as a whole (shipping documents sent).
    """

    __tablename__ = "deal_milestone"

    id: Mapped[uuid.UUID] = uuid_pk()
    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("deal.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deal_party_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("deal_party.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    planned_date: Mapped[date | None] = mapped_column(Date, index=True)
    actual_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[MilestoneStatus] = mapped_column(
        String(16), nullable=False, default=MilestoneStatus.PENDING,
        server_default=MilestoneStatus.PENDING.value, index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    deal: Mapped[Deal] = relationship(back_populates="milestones")

    __table_args__ = (
        CheckConstraint(
            "status <> 'DONE' OR actual_date IS NOT NULL", name="milestone_done_needs_date"
        ),
        Index("ix_milestone_due", "status", "planned_date"),
    )

    @property
    def is_overdue(self) -> bool:
        if self.status in {MilestoneStatus.DONE, MilestoneStatus.SKIPPED}:
            return False
        return self.planned_date is not None and self.planned_date < date.today()
