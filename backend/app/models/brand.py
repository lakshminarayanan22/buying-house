"""Brand profile (§4.2).

Brand onboarding captures a *constraint set*, not a wish list. Everything here is applied as
a per-brand filter layer before §10 scoring runs: a brand that mandates GOTS and refuses a
country should never see a supplier who fails either test, however well the supplier scores.
"""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import MarketSegment, ReferenceDomain
from app.models.base import (
    Base,
    TimestampMixin,
    reference_domain_col,
    reference_fk,
    reference_id_col,
    uuid_pk,
)


class BrandProfile(Base, TimestampMixin):
    __tablename__ = "brand_profile"

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True
    )

    market_segment: Mapped[MarketSegment | None] = mapped_column(String(20), index=True)
    annual_volume_band: Mapped[str | None] = mapped_column(String(40))

    preferred_incoterm_id: Mapped[uuid.UUID | None] = reference_id_col(nullable=True)
    preferred_incoterm_domain: Mapped[str | None] = reference_domain_col(
        ReferenceDomain.INCOTERM, nullable=True
    )
    default_currency_id: Mapped[uuid.UUID | None] = reference_id_col(nullable=True)
    default_currency_domain: Mapped[str | None] = reference_domain_col(
        ReferenceDomain.CURRENCY, nullable=True
    )
    payment_terms_standard: Mapped[str | None] = mapped_column(String(200))

    sustainability_requirements: Mapped[str | None] = mapped_column(Text)
    packaging_standards: Mapped[str | None] = mapped_column(Text)

    # Uploaded once at onboarding, referenced on every enquiry rather than re-attached.
    qa_protocol_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )
    vendor_manual_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )
    tech_pack_template_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )

    completeness_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        *reference_fk("brand_profile", "preferred_incoterm", ReferenceDomain.INCOTERM),
        *reference_fk("brand_profile", "default_currency", ReferenceDomain.CURRENCY),
        CheckConstraint(
            "completeness_pct >= 0 AND completeness_pct <= 100",
            name="brand_profile_completeness_range",
        ),
    )


class BrandCategory(Base, TimestampMixin):
    """Product categories this brand buys."""

    __tablename__ = "brand_category"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    product_category_id: Mapped[uuid.UUID] = reference_id_col()
    product_category_domain: Mapped[str] = reference_domain_col(ReferenceDomain.PRODUCT_CATEGORY)

    __table_args__ = (
        *reference_fk("brand_category", "product_category", ReferenceDomain.PRODUCT_CATEGORY),
        UniqueConstraint("org_id", "product_category_id", name="uq_brand_category_org_cat"),
    )


class BrandTargetMarket(Base, TimestampMixin):
    """Countries the brand sells into — drives which compliance regimes apply."""

    __tablename__ = "brand_target_market"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    country_id: Mapped[uuid.UUID] = reference_id_col()
    country_domain: Mapped[str] = reference_domain_col(ReferenceDomain.COUNTRY)

    __table_args__ = (
        *reference_fk("brand_target_market", "country", ReferenceDomain.COUNTRY),
        UniqueConstraint("org_id", "country_id", name="uq_brand_target_market_org_country"),
    )


class BrandRequiredCertification(Base, TimestampMixin):
    """A certification the brand requires of its suppliers.

    `is_mandatory` separates a hard filter from a preference: mandatory eliminates a supplier
    in §10 step 2, preferred only contributes to the 8% compliance weight in step 3. Collapsing
    the two is how a matcher ends up either recommending non-compliant factories or returning
    nothing at all.
    """

    __tablename__ = "brand_required_certification"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    certification_id: Mapped[uuid.UUID] = reference_id_col()
    certification_domain: Mapped[str] = reference_domain_col(ReferenceDomain.CERTIFICATION)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        *reference_fk("brand_required_certification", "certification", ReferenceDomain.CERTIFICATION),
        UniqueConstraint("org_id", "certification_id", name="uq_brand_req_cert_org_cert"),
    )


class BrandExcludedCountry(Base, TimestampMixin):
    """Countries a brand will not source from. A hard filter, and a common one in practice."""

    __tablename__ = "brand_excluded_country"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    country_id: Mapped[uuid.UUID] = reference_id_col()
    country_domain: Mapped[str] = reference_domain_col(ReferenceDomain.COUNTRY)
    reason: Mapped[str | None] = mapped_column(String(300))

    __table_args__ = (
        *reference_fk("brand_excluded_country", "country", ReferenceDomain.COUNTRY),
        UniqueConstraint("org_id", "country_id", name="uq_brand_excluded_country_org_country"),
    )
