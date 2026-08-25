"""The commercial record: which brands we connected to which suppliers, and what we earned.

This is the third pillar. `organization` says who exists and `supplier_process` says what a
factory can do; this says what business actually happened.

The shape follows how the work is really done. A brand rarely needs a whole supply chain — they
need the part they are missing. Sometimes that is garmenting alone because the fabric is
already sourced; sometimes it is knitting and dyeing because they have their own stitching
unit. So a Connection is one brand requirement, and it carries one line per *stage* of the
chain we are covering. A single-supplier deal is a chain of one, and no schema change stands
between the two cases.

Deliberately not modelled as an Enquiry -> Quotation -> Order chain yet. At a handful of
connections a month, four tables where one will do is cost without benefit; the lifecycle can
grow out of this when volume justifies it.
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
    ChainStageStatus,
    CommissionBasis,
    CommissionStatus,
    ConnectionStatus,
    ReferenceDomain,
)
from app.models.base import (
    Base,
    TimestampMixin,
    reference_domain_col,
    reference_fk,
    reference_id_col,
    uuid_pk,
)


class Connection(Base, TimestampMixin):
    """One brand requirement that we are solving with our suppliers."""

    __tablename__ = "connection"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Human reference for phone calls and invoices — CN-2026-0007.
    connection_no: Mapped[str] = mapped_column(String(24), nullable=False)

    brand_org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    product_category_id: Mapped[uuid.UUID | None] = reference_id_col(nullable=True)
    product_category_domain: Mapped[str | None] = reference_domain_col(
        ReferenceDomain.PRODUCT_CATEGORY, nullable=True
    )
    currency_id: Mapped[uuid.UUID | None] = reference_id_col(nullable=True)
    currency_domain: Mapped[str | None] = reference_domain_col(
        ReferenceDomain.CURRENCY, nullable=True
    )

    status: Mapped[ConnectionStatus] = mapped_column(
        String(20), nullable=False, default=ConnectionStatus.SCOPING,
        server_default=ConnectionStatus.SCOPING.value, index=True,
    )
    lost_reason: Mapped[str | None] = mapped_column(String(400))

    target_ship_date: Mapped[date | None] = mapped_column(Date, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Who on our side owns it. The "my desk" view keys on this.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL"), index=True
    )

    stages: Mapped[list["ConnectionStage"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan",
        order_by="ConnectionStage.sequence",
    )

    __table_args__ = (
        UniqueConstraint("connection_no", name="uq_connection_no"),
        *reference_fk("connection", "product_category", ReferenceDomain.PRODUCT_CATEGORY),
        *reference_fk("connection", "currency", ReferenceDomain.CURRENCY),
        CheckConstraint(
            "status <> 'LOST' OR lost_reason IS NOT NULL",
            name="connection_lost_needs_reason",
        ),
        Index("ix_connection_status_ship", "status", "target_ship_date"),
    )

    @property
    def commission_total(self) -> float:
        return float(sum(s.commission_amount or 0 for s in self.stages))

    @property
    def order_value_total(self) -> float:
        return float(sum(s.order_value or 0 for s in self.stages))


class ConnectionStage(Base, TimestampMixin):
    """One stage of the chain, covered by one supplier, with what we earn on it.

    `process_type` is what makes this work: it says *which part* of the chain this supplier is
    covering — knitting, dyeing, garmenting — so a connection that only needs garmenting has
    one row and a connection that needs yarn through finishing has five, without either being
    a special case.

    Money lives here rather than on the connection because the basis genuinely varies stage by
    stage: a commission from the mill on fabric, a markup on the garment price.
    """

    __tablename__ = "connection_stage"

    id: Mapped[uuid.UUID] = uuid_pk()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("connection.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    supplier_org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    process_type_id: Mapped[uuid.UUID] = reference_id_col()
    process_type_domain: Mapped[str] = reference_domain_col(ReferenceDomain.PROCESS_TYPE)
    # Position in the chain: yarn before knitting before dyeing before garmenting.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    status: Mapped[ChainStageStatus] = mapped_column(
        String(20), nullable=False, default=ChainStageStatus.PROPOSED,
        server_default=ChainStageStatus.PROPOSED.value, index=True,
    )

    qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    qty_uom: Mapped[str | None] = mapped_column(String(20))

    # Per unit. supplier_price is what the factory is paid; brand_price is what we quote.
    # The gap between them is the whole business on a markup deal, which is why a brand user
    # must never be able to read supplier_price — enforced in the access-control layer, where
    # Connection and ConnectionStage are internal-only.
    supplier_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    brand_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    order_value: Mapped[float | None] = mapped_column(Numeric(14, 2))

    commission_basis: Mapped[CommissionBasis] = mapped_column(
        String(24), nullable=False, default=CommissionBasis.SUPPLIER_COMMISSION,
        server_default=CommissionBasis.SUPPLIER_COMMISSION.value,
    )
    commission_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    commission_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    commission_status: Mapped[CommissionStatus] = mapped_column(
        String(20), nullable=False, default=CommissionStatus.NOT_DUE,
        server_default=CommissionStatus.NOT_DUE.value, index=True,
    )
    invoiced_on: Mapped[date | None] = mapped_column(Date)
    received_on: Mapped[date | None] = mapped_column(Date, index=True)

    ship_date: Mapped[date | None] = mapped_column(Date, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    connection: Mapped[Connection] = relationship(back_populates="stages")

    __table_args__ = (
        *reference_fk("connection_stage", "process_type", ReferenceDomain.PROCESS_TYPE),
        # One supplier may cover two stages of the same deal (a mill that knits and dyes), but
        # not the same stage twice.
        UniqueConstraint(
            "connection_id", "supplier_org_id", "process_type_id",
            name="uq_connection_stage_supplier_process",
        ),
        CheckConstraint(
            "commission_basis <> 'SUPPLIER_COMMISSION' OR commission_pct IS NOT NULL",
            name="connection_stage_commission_needs_pct",
        ),
        # A markup deal is defined by the two prices; without both there is no margin to record.
        CheckConstraint(
            "commission_basis <> 'BRAND_MARKUP' "
            "OR (supplier_price IS NOT NULL AND brand_price IS NOT NULL)",
            name="connection_stage_markup_needs_prices",
        ),
        CheckConstraint(
            "brand_price IS NULL OR supplier_price IS NULL OR brand_price >= supplier_price",
            name="connection_stage_markup_not_negative",
        ),
        CheckConstraint(
            "commission_amount IS NULL OR commission_amount >= 0",
            name="connection_stage_commission_not_negative",
        ),
        CheckConstraint(
            "commission_status NOT IN ('INVOICED','RECEIVED') OR commission_amount IS NOT NULL",
            name="connection_stage_billed_needs_amount",
        ),
        CheckConstraint(
            "received_on IS NULL OR invoiced_on IS NULL OR received_on >= invoiced_on",
            name="connection_stage_received_after_invoiced",
        ),
        Index("ix_connection_stage_ledger", "commission_status", "received_on"),
        Index("ix_connection_stage_supplier", "supplier_org_id", "status"),
    )

    def compute_commission(self) -> float | None:
        """Derive what we earn on this stage from its basis.

        Returned rather than assigned so the caller decides whether to overwrite a figure a
        merchandiser typed in by hand — a negotiated number should survive a recalculation.
        """
        if self.commission_basis == CommissionBasis.SUPPLIER_COMMISSION:
            if self.order_value is None or self.commission_pct is None:
                return None
            return round(float(self.order_value) * float(self.commission_pct) / 100, 2)
        if self.commission_basis == CommissionBasis.BRAND_MARKUP:
            if self.brand_price is None or self.supplier_price is None or self.qty is None:
                return None
            return round(
                (float(self.brand_price) - float(self.supplier_price)) * float(self.qty), 2
            )
        return 0.0
