"""Supplier profile — §4.3, the heart of the system and the agent's feature store.

Every self-reported table here carries `source` (DataSource). Onboarding answers are a
*prior*, not a fact: they let a brand-new factory enter the candidate set on day one
(§10 cold-start) and are progressively overridden by observed outcomes from Phases 3-5.
Scoring can therefore discount a claim no transaction has ever confirmed.
"""
import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    CapacityUom,
    DataSource,
    ReferenceDomain,
    SubcontractingPolicy,
    SupplierTier,
    VerificationStatus,
)
from app.models.base import (
    Base,
    JSONVariant,
    TimestampMixin,
    reference_domain_col,
    reference_fk,
    reference_id_col,
    uuid_pk,
)


class SupplierProfile(Base, TimestampMixin):
    """One row per supplier org: the facts that are not per-process or per-product."""

    __tablename__ = "supplier_profile"

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True
    )

    # Internal grading. Deliberately never exposed to the supplier.
    supplier_tier_grade: Mapped[str | None] = mapped_column(String(2))
    completeness_tier: Mapped[SupplierTier] = mapped_column(
        String(30), nullable=False, default=SupplierTier.TIER_1_REGISTERED,
        server_default=SupplierTier.TIER_1_REGISTERED.value, index=True,
    )
    # 0-100, recomputed on save. §5.2: incomplete profiles are invisible to the matcher, so
    # this number drives the nudge campaign rather than just decorating the dashboard.
    completeness_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    export_experience_years: Mapped[int | None] = mapped_column(Integer)
    annual_turnover_band: Mapped[str | None] = mapped_column(String(40))
    is_vertically_integrated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    subcontracting_policy: Mapped[SubcontractingPolicy | None] = mapped_column(String(30))

    # Free-text, deliberately. "Describe the work you are known for" is the one onboarding
    # answer that should NOT be forced into the taxonomy: it is the input to the Phase 6
    # semantic re-rank (§10 step 4), which exists precisely to catch the nuance the structured
    # fields miss. The pgvector column is added in Phase 6; the text it embeds is captured now,
    # because you cannot backfill an answer nobody was asked.
    capability_narrative: Mapped[str | None] = mapped_column(Text)
    narrative_language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )

    source: Mapped[DataSource] = mapped_column(
        String(20), nullable=False, default=DataSource.SELF_REPORTED,
        server_default=DataSource.SELF_REPORTED.value,
    )

    processes: Mapped[list["SupplierProcess"]] = relationship(
        primaryjoin="SupplierProfile.org_id == foreign(SupplierProcess.org_id)",
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            "completeness_pct >= 0 AND completeness_pct <= 100",
            name="supplier_profile_completeness_range",
        ),
    )


class SupplierExportMarket(Base, TimestampMixin):
    """Countries this supplier already ships to — a hard filter for brands with market rules."""

    __tablename__ = "supplier_export_market"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    country_id: Mapped[uuid.UUID] = reference_id_col()
    country_domain: Mapped[str] = reference_domain_col(ReferenceDomain.COUNTRY)
    years_shipping: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        *reference_fk("supplier_export_market", "country", ReferenceDomain.COUNTRY),
        UniqueConstraint("org_id", "country_id", name="uq_supplier_export_market_org_country"),
    )


class SupplierProcess(Base, TimestampMixin):
    """One row per process the factory performs (§4.3).

    This is the primary hard filter in §10 step 2: a supplier who cannot dye cannot be
    recommended for a dyeing job, no matter how good the semantic similarity looks.
    """

    __tablename__ = "supplier_process"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    process_type_id: Mapped[uuid.UUID] = reference_id_col()
    process_type_domain: Mapped[str] = reference_domain_col(ReferenceDomain.PROCESS_TYPE)

    is_inhouse: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_subcontracted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    subcontractor_notes: Mapped[str | None] = mapped_column(Text)

    monthly_capacity_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    capacity_uom: Mapped[CapacityUom | None] = mapped_column(String(20))
    min_order_qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    moq_uom: Mapped[CapacityUom | None] = mapped_column(String(20))

    standard_lead_time_days: Mapped[int | None] = mapped_column(Integer)
    sample_lead_time_days: Mapped[int | None] = mapped_column(Integer)

    source: Mapped[DataSource] = mapped_column(
        String(20), nullable=False, default=DataSource.SELF_REPORTED,
        server_default=DataSource.SELF_REPORTED.value,
    )

    __table_args__ = (
        *reference_fk("supplier_process", "process_type", ReferenceDomain.PROCESS_TYPE),
        UniqueConstraint("org_id", "process_type_id", name="uq_supplier_process_org_process"),
        CheckConstraint(
            "is_inhouse OR is_subcontracted", name="supplier_process_inhouse_or_subcontracted"
        ),
        CheckConstraint(
            "monthly_capacity_value IS NULL OR capacity_uom IS NOT NULL",
            name="supplier_process_capacity_needs_uom",
        ),
        CheckConstraint(
            "min_order_qty IS NULL OR moq_uom IS NOT NULL",
            name="supplier_process_moq_needs_uom",
        ),
        Index("ix_supplier_process_filter", "process_type_id", "org_id"),
    )


class SupplierCapability(Base, TimestampMixin):
    """What the factory can actually make, per product category (§4.3).

    Feeds both the step-2 filter and the 25% capability-fit weight in §10 step 3.
    """

    __tablename__ = "supplier_capability"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    product_category_id: Mapped[uuid.UUID] = reference_id_col()
    product_category_domain: Mapped[str] = reference_domain_col(ReferenceDomain.PRODUCT_CATEGORY)

    gsm_min: Mapped[int | None] = mapped_column(Integer)
    gsm_max: Mapped[int | None] = mapped_column(Integer)
    size_range: Mapped[str | None] = mapped_column(String(160))

    price_band_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    price_band_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency_id: Mapped[uuid.UUID | None] = reference_id_col(nullable=True)
    currency_domain: Mapped[str | None] = reference_domain_col(
        ReferenceDomain.CURRENCY, nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[DataSource] = mapped_column(
        String(20), nullable=False, default=DataSource.SELF_REPORTED,
        server_default=DataSource.SELF_REPORTED.value,
    )

    fibres: Mapped[list["SupplierCapabilityFibre"]] = relationship(
        back_populates="capability", cascade="all, delete-orphan"
    )
    constructions: Mapped[list["SupplierCapabilityConstruction"]] = relationship(
        back_populates="capability", cascade="all, delete-orphan"
    )

    __table_args__ = (
        *reference_fk("supplier_capability", "product_category", ReferenceDomain.PRODUCT_CATEGORY),
        *reference_fk("supplier_capability", "currency", ReferenceDomain.CURRENCY),
        UniqueConstraint("org_id", "product_category_id", name="uq_supplier_capability_org_cat"),
        CheckConstraint(
            "gsm_min IS NULL OR gsm_max IS NULL OR gsm_min <= gsm_max",
            name="supplier_capability_gsm_order",
        ),
        CheckConstraint(
            "price_band_min IS NULL OR price_band_max IS NULL OR price_band_min <= price_band_max",
            name="supplier_capability_price_order",
        ),
        CheckConstraint(
            "(price_band_min IS NULL AND price_band_max IS NULL) OR currency_id IS NOT NULL",
            name="supplier_capability_price_needs_currency",
        ),
    )


class SupplierCapabilityFibre(Base, TimestampMixin):
    """Fibres a capability covers. An association table, not an array, so the directory can
    facet on it with an index instead of scanning every row."""

    __tablename__ = "supplier_capability_fibre"

    id: Mapped[uuid.UUID] = uuid_pk()
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("supplier_capability.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    fibre_id: Mapped[uuid.UUID] = reference_id_col()
    fibre_domain: Mapped[str] = reference_domain_col(ReferenceDomain.FIBRE)

    capability: Mapped[SupplierCapability] = relationship(back_populates="fibres")

    __table_args__ = (
        *reference_fk("supplier_capability_fibre", "fibre", ReferenceDomain.FIBRE),
        UniqueConstraint("capability_id", "fibre_id", name="uq_supplier_cap_fibre"),
    )


class SupplierCapabilityConstruction(Base, TimestampMixin):
    """Fabric constructions a capability covers (Single Jersey, Rib, French Terry, ...)."""

    __tablename__ = "supplier_capability_construction"

    id: Mapped[uuid.UUID] = uuid_pk()
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("supplier_capability.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    construction_id: Mapped[uuid.UUID] = reference_id_col()
    construction_domain: Mapped[str] = reference_domain_col(ReferenceDomain.FABRIC_CONSTRUCTION)

    capability: Mapped[SupplierCapability] = relationship(back_populates="constructions")

    __table_args__ = (
        *reference_fk(
            "supplier_capability_construction", "construction", ReferenceDomain.FABRIC_CONSTRUCTION
        ),
        UniqueConstraint("capability_id", "construction_id", name="uq_supplier_cap_construction"),
    )


class SupplierMachine(Base, TimestampMixin):
    """Machinery list — Tier 2. The basis for real capacity modelling later."""

    __tablename__ = "supplier_machine"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    machine_type_id: Mapped[uuid.UUID] = reference_id_col()
    machine_type_domain: Mapped[str] = reference_domain_col(ReferenceDomain.MACHINERY_TYPE)

    make: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    gauge: Mapped[str | None] = mapped_column(String(40))
    diameter: Mapped[str | None] = mapped_column(String(40))
    year_of_make: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str | None] = mapped_column(String(40))

    source: Mapped[DataSource] = mapped_column(
        String(20), nullable=False, default=DataSource.SELF_REPORTED,
        server_default=DataSource.SELF_REPORTED.value,
    )

    __table_args__ = (
        *reference_fk("supplier_machine", "machine_type", ReferenceDomain.MACHINERY_TYPE),
        CheckConstraint("count > 0", name="supplier_machine_count_positive"),
    )


class SupplierCertification(Base, TimestampMixin):
    """A held certification with its validity window (§4.3).

    `valid_till` is a hard filter in §10 step 2 — an expired GOTS certificate must remove the
    supplier from a GOTS enquiry automatically, not wait for someone to notice.
    """

    __tablename__ = "supplier_certification"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    certification_id: Mapped[uuid.UUID] = reference_id_col()
    certification_domain: Mapped[str] = reference_domain_col(ReferenceDomain.CERTIFICATION)

    certificate_no: Mapped[str | None] = mapped_column(String(120))
    issuing_body: Mapped[str | None] = mapped_column(String(200))
    scope: Mapped[str | None] = mapped_column(Text)
    issued_on: Mapped[date | None] = mapped_column(Date)
    valid_till: Mapped[date | None] = mapped_column(Date, index=True)

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        String(20), nullable=False, default=VerificationStatus.PENDING,
        server_default=VerificationStatus.PENDING.value, index=True,
    )
    source: Mapped[DataSource] = mapped_column(
        String(20), nullable=False, default=DataSource.SELF_REPORTED,
        server_default=DataSource.SELF_REPORTED.value,
    )

    __table_args__ = (
        *reference_fk("supplier_certification", "certification", ReferenceDomain.CERTIFICATION),
        UniqueConstraint(
            "org_id", "certification_id", "certificate_no", name="uq_supplier_cert_org_cert_no"
        ),
        Index("ix_supplier_cert_active", "org_id", "certification_id", "valid_till"),
    )

    def is_valid_on(self, on: date) -> bool:
        """Held, verified, and unexpired on a given date — the exact §10 step-2 predicate."""
        if self.verification_status != VerificationStatus.VERIFIED:
            return False
        return self.valid_till is None or self.valid_till >= on


class SupplierCompliance(Base, TimestampMixin):
    """A social/environmental audit record — Tier 3 (§4.3)."""

    __tablename__ = "supplier_compliance"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    audit_type_id: Mapped[uuid.UUID] = reference_id_col()
    audit_type_domain: Mapped[str] = reference_domain_col(ReferenceDomain.COMPLIANCE_AUDIT_TYPE)

    audit_body: Mapped[str | None] = mapped_column(String(200))
    audit_date: Mapped[date | None] = mapped_column(Date)
    grade: Mapped[str | None] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    findings_summary: Mapped[str | None] = mapped_column(Text)
    capa_status: Mapped[str | None] = mapped_column(String(40))
    next_audit_due: Mapped[date | None] = mapped_column(Date, index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )

    __table_args__ = (
        *reference_fk("supplier_compliance", "audit_type", ReferenceDomain.COMPLIANCE_AUDIT_TYPE),
    )


class SupplierCapacityCalendar(Base, TimestampMixin):
    """Month-wise booked vs free capacity, per process (§4.3).

    §11: matching without knowing who is free in October produces confident, useless
    recommendations. `month` is stored as the first day of the month.
    """

    __tablename__ = "supplier_capacity_calendar"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    process_type_id: Mapped[uuid.UUID] = reference_id_col()
    process_type_domain: Mapped[str] = reference_domain_col(ReferenceDomain.PROCESS_TYPE)

    month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    committed_qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    available_qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    uom: Mapped[CapacityUom | None] = mapped_column(String(20))

    source: Mapped[DataSource] = mapped_column(
        String(20), nullable=False, default=DataSource.SELF_REPORTED,
        server_default=DataSource.SELF_REPORTED.value,
    )

    __table_args__ = (
        *reference_fk("supplier_capacity_calendar", "process_type", ReferenceDomain.PROCESS_TYPE),
        UniqueConstraint(
            "org_id", "process_type_id", "month", name="uq_supplier_capacity_org_process_month"
        ),
    )


class SupplierReference(Base, TimestampMixin):
    """Past work the supplier claims, captured at onboarding.

    Pure cold-start material (§10): a factory with no order history in our system still has a
    history somewhere. Structured enough to filter on, and its `description` is a second input
    to the Phase 6 semantic re-rank. Marked SELF_REPORTED until someone actually checks a
    reference, which is exactly the distinction `source` exists to preserve.
    """

    __tablename__ = "supplier_reference"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    buyer_name: Mapped[str | None] = mapped_column(String(200))
    buyer_country_id: Mapped[uuid.UUID | None] = reference_id_col(nullable=True)
    buyer_country_domain: Mapped[str | None] = reference_domain_col(
        ReferenceDomain.COUNTRY, nullable=True
    )
    product_category_id: Mapped[uuid.UUID | None] = reference_id_col(nullable=True)
    product_category_domain: Mapped[str | None] = reference_domain_col(
        ReferenceDomain.PRODUCT_CATEGORY, nullable=True
    )
    annual_qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    qty_uom: Mapped[CapacityUom | None] = mapped_column(String(20))
    year: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)

    is_contactable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        String(20), nullable=False, default=VerificationStatus.PENDING,
        server_default=VerificationStatus.PENDING.value,
    )

    __table_args__ = (
        *reference_fk("supplier_reference", "buyer_country", ReferenceDomain.COUNTRY),
        *reference_fk("supplier_reference", "product_category", ReferenceDomain.PRODUCT_CATEGORY),
    )


class SupplierPerformance(Base, TimestampMixin):
    """Computed nightly from real transactions (§4.3, Phase 5). Never written by a supplier.

    These columns carry ~52% of the §10 weight table, and none of them can be asked at
    onboarding — a factory's own OTD number is marketing copy. The table exists from day one
    so the rollup job and the scorer have a stable target; it simply stays empty until orders
    start flowing. `source` is fixed to OBSERVED by a check constraint, which is the whole
    point of the column's existence.
    """

    __tablename__ = "supplier_performance"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # First day of the period; `period_months` distinguishes a month from a rolling quarter.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_months: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    orders_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    on_time_delivery_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    avg_delay_days: Mapped[float | None] = mapped_column(Numeric(6, 2))
    final_inspection_pass_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    defect_rate_ppm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    sample_approval_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    avg_sample_turnaround_days: Mapped[float | None] = mapped_column(Numeric(6, 2))
    quote_response_time_hrs: Mapped[float | None] = mapped_column(Numeric(8, 2))
    quote_win_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    price_competitiveness_index: Mapped[float | None] = mapped_column(Numeric(6, 3))
    claims_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    composite_score: Mapped[float | None] = mapped_column(Numeric(6, 2))

    # How much history the numbers rest on. A 100% OTD over one order is not a 100% OTD, and
    # the scorer must be able to tell the difference instead of rewarding a lucky first job.
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    components: Mapped[dict | None] = mapped_column(JSONVariant)

    __table_args__ = (
        UniqueConstraint(
            "org_id", "period_start", "period_months", name="uq_supplier_performance_org_period"
        ),
    )
