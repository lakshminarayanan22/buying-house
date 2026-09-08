"""Companies — everyone we deal with, on either side.

Not "brands" and "suppliers". An Indian spinning mill buys Australian cotton from us and sells
yarn onward; a Japanese chemical company supplies an input and is nobody's supplier in the
apparel sense. Which side of a transaction a company sits on is a property of the *deal*, not
of the company, so it lives on DealParty.

`buys` and `sells` are hints for filtering a list, not a constraint on what a company may do.
"""
import uuid

from sqlalchemy import (
    Boolean,
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

from app.enums import CompanyStatus
from app.models.base import Base, TimestampMixin, uuid_pk


class Company(Base, TimestampMixin):
    __tablename__ = "company"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(240))

    country_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT"), index=True
    )
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(240))

    # Which way they usually trade. A mill has both true.
    buys: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    sells: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    status: Mapped[CompanyStatus] = mapped_column(
        String(16), nullable=False, default=CompanyStatus.LEAD,
        server_default=CompanyStatus.LEAD.value, index=True,
    )

    tax_id: Mapped[str | None] = mapped_column(String(40))   # GST, ABN, whatever their country uses
    year_established: Mapped[int | None] = mapped_column(Integer)

    # --- what we remember about them as a buyer ---
    payment_terms: Mapped[str | None] = mapped_column(String(300))
    quality_requirements: Mapped[str | None] = mapped_column(Text)

    # --- what we remember about them as a seller ---
    # Capacity and machinery as prose rather than as rows. The detail that matters lives in the
    # factory brochure; these are the two lines a merchandiser wants on screen without opening it.
    capacity_notes: Mapped[str | None] = mapped_column(Text)
    machinery_notes: Mapped[str | None] = mapped_column(Text)
    moq_notes: Mapped[str | None] = mapped_column(String(300))
    lead_time_notes: Mapped[str | None] = mapped_column(String(300))

    # The factory profile PDF is not a column here. Pointing at it would put company and
    # document in a foreign-key cycle, and a cycle costs a use_alter constraint that Alembic
    # silently drops. It is simply the newest document for this company with kind=BROCHURE —
    # one query, no cycle, and a company can keep older versions without a "which one" problem.

    notes: Mapped[str | None] = mapped_column(Text)

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    processes: Mapped[list["CompanyProcess"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    products: Mapped[list["CompanyProduct"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    certifications: Mapped[list["CompanyCertification"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    clients: Mapped[list["CompanyClient"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Nothing enforces this nationally, but a duplicate factory in a list of ten is worse
        # than a rejected insert.
        UniqueConstraint("name", "city", name="uq_company_name_city"),
        Index("ix_company_role_status", "sells", "buys", "status"),
    )


class Contact(Base, TimestampMixin):
    """A person at a company. Most of them will never log in — they are phone numbers."""

    __tablename__ = "contact"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(240))
    phone: Mapped[str | None] = mapped_column(String(30))
    whatsapp: Mapped[str | None] = mapped_column(String(30))
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    notes: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company] = relationship(back_populates="contacts")


class CompanyProcess(Base, TimestampMixin):
    """A stage of the chain this company performs, with the two numbers worth filtering on.

    One row per process: a mill that knits and dyes has two. Everything richer — machine counts,
    shift patterns — stays in the brochure.
    """

    __tablename__ = "company_process"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    process_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    monthly_capacity: Mapped[float | None] = mapped_column(Numeric(14, 2))
    min_order_qty: Mapped[float | None] = mapped_column(Numeric(14, 2))
    uom: Mapped[str | None] = mapped_column(String(20))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company] = relationship(back_populates="processes")

    __table_args__ = (
        UniqueConstraint("company_id", "process_id", name="uq_company_process"),
    )


class CompanyProduct(Base, TimestampMixin):
    """What they mostly make — t-shirts, polos, innerwear, or raw cotton and yarn."""

    __tablename__ = "company_product"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    company: Mapped[Company] = relationship(back_populates="products")

    __table_args__ = (UniqueConstraint("company_id", "product_id", name="uq_company_product"),)


class CompanyCertification(Base, TimestampMixin):
    """Held certifications, by name only.

    No expiry dates, no verification workflow, no certificate PDFs — the answer was that names
    alone suffice for reference. If a brand ever asks for proof, that is a phone call.
    """

    __tablename__ = "company_certification"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    certification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    reference_no: Mapped[str | None] = mapped_column(String(120))

    company: Mapped[Company] = relationship(back_populates="certifications")

    __table_args__ = (
        UniqueConstraint("company_id", "certification_id", name="uq_company_certification"),
    )


class CompanyClient(Base, TimestampMixin):
    """Brands this company works for, past and present.

    Free text on purpose: these are Zara and Uniqlo, not rows in our own company table, and
    pretending otherwise would mean creating a company record for every name a factory mentions.
    """

    __tablename__ = "company_client"

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notes: Mapped[str | None] = mapped_column(String(300))

    company: Mapped[Company] = relationship(back_populates="clients")

    __table_args__ = (
        UniqueConstraint("company_id", "client_name", name="uq_company_client"),
    )
