"""Request and response shapes. One file — the API surface is small enough to read at once."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import (
    CommissionBasis,
    CommissionStatus,
    CompanyStatus,
    DealRole,
    DealStatus,
    DocumentKind,
    MilestoneStatus,
    UserRole,
    UserStatus,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Msg(BaseModel):
    detail: str


# ------------------------------------------------------------------------- auth
class LoginBody(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=200)


class Session(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Me(ORM):
    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    avatar_url: str | None = None
    has_password: bool = False
    # Linked to a Google account. Always true for anyone who arrived through Google; false
    # only for accounts created before Google sign-in existed (the demo seed).
    google_linked: bool = False


class AuthConfig(BaseModel):
    """What the login screen needs to render itself. Public: it holds nothing secret — a
    Google OAuth client id is designed to be shipped to browsers."""

    google_backend: str                # "google" | "stub"
    google_client_id: str | None
    allowed_domain: str
    password_login: bool = True


class GoogleSignInBody(BaseModel):
    credential: str = Field(min_length=1, max_length=8192)


class SignInResult(BaseModel):
    """The outcome of a Google sign-in.

    Every recognised state is a 200 with a status, not an error code: "you're waiting for
    approval" is a normal, expected answer the login screen draws a page for. Only ACTIVE
    carries a token — a pending account can prove who it is but can't touch anything.
    """

    status: UserStatus
    access_token: str | None = None
    name: str
    email: str
    message: str
    newly_requested: bool = False


class PasswordBody(BaseModel):
    current_password: str | None = Field(None, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class TeamMember(ORM):
    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    status: UserStatus
    avatar_url: str | None
    has_password: bool
    google_linked: bool
    created_at: datetime
    last_login_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by_name: str | None = None


class ApproveBody(BaseModel):
    role: UserRole = UserRole.MEMBER


class RoleBody(BaseModel):
    role: UserRole


# --------------------------------------------------------------------- taxonomy
class RefOut(ORM):
    id: uuid.UUID
    domain: str
    code: str
    name: str
    aliases: list[str] = []
    parent_id: uuid.UUID | None = None


# --------------------------------------------------------------------- company
class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    designation: str | None = None
    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    is_primary: bool = False


class ContactOut(ContactIn, ORM):
    id: uuid.UUID


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    legal_name: str | None = None
    country_code: str | None = None
    city: str | None = None
    address: str | None = None
    website: str | None = None
    buys: bool = False
    sells: bool = True
    status: CompanyStatus = CompanyStatus.LEAD
    tax_id: str | None = None
    payment_terms: str | None = None
    quality_requirements: str | None = None
    capacity_notes: str | None = None
    machinery_notes: str | None = None
    moq_notes: str | None = None
    lead_time_notes: str | None = None
    notes: str | None = None


class CompanyRow(ORM):
    id: uuid.UUID
    name: str
    city: str | None
    country_id: uuid.UUID | None
    buys: bool
    sells: bool
    status: CompanyStatus
    processes: list[str] = []
    products: list[str] = []
    certifications: list[str] = []
    has_brochure: bool = False


class CompanyDetail(CompanyRow):
    legal_name: str | None = None
    address: str | None = None
    website: str | None = None
    tax_id: str | None = None
    payment_terms: str | None = None
    quality_requirements: str | None = None
    capacity_notes: str | None = None
    machinery_notes: str | None = None
    moq_notes: str | None = None
    lead_time_notes: str | None = None
    notes: str | None = None
    contacts: list[ContactOut] = []
    clients: list[str] = []
    open_deals: int = 0


class ProcessIn(BaseModel):
    process_code: str
    monthly_capacity: float | None = None
    min_order_qty: float | None = None
    uom: str | None = None
    lead_time_days: int | None = None
    notes: str | None = None


class TagIn(BaseModel):
    """A product, a certification, or a client name — whichever list is being added to."""

    code: str | None = None
    name: str | None = None


# ------------------------------------------------------------------------ deal
class PartyIn(BaseModel):
    company_id: uuid.UUID
    role: DealRole
    process_code: str | None = None
    sequence: int = 1
    qty: float | None = None
    uom: str | None = None
    unit_price: float | None = None
    resale_unit_price: float | None = None
    value: float | None = None
    commission_basis: CommissionBasis = CommissionBasis.NONE
    commission_pct: float | None = None
    commission_amount: float | None = None
    commission_status: CommissionStatus = CommissionStatus.NOT_DUE
    invoiced_on: date | None = None
    received_on: date | None = None
    ship_date: date | None = None
    notes: str | None = None


class PartyOut(ORM):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str | None = None
    role: DealRole
    process_name: str | None = None
    sequence: int
    qty: float | None
    uom: str | None
    unit_price: float | None
    resale_unit_price: float | None
    value: float | None
    commission_basis: CommissionBasis
    commission_pct: float | None
    commission_amount: float | None
    commission_status: CommissionStatus
    invoiced_on: date | None
    received_on: date | None
    ship_date: date | None
    notes: str | None


class MilestoneIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    sequence: int = 1
    planned_date: date | None = None
    actual_date: date | None = None
    status: MilestoneStatus = MilestoneStatus.PENDING
    notes: str | None = None


class MilestoneOut(MilestoneIn, ORM):
    id: uuid.UUID
    is_overdue: bool = False


class DealIn(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    description: str | None = None
    product_code: str | None = None
    currency_code: str | None = None
    incoterm_code: str | None = None
    status: DealStatus = DealStatus.LEAD
    lost_reason: str | None = None
    target_ship_date: date | None = None
    notes: str | None = None


class DealRow(ORM):
    id: uuid.UUID
    deal_no: str
    title: str
    status: DealStatus
    target_ship_date: date | None
    last_activity_at: datetime | None
    value: float = 0
    commission: float = 0
    party_count: int = 0
    counterparties: list[str] = []


class DealDetail(DealRow):
    description: str | None = None
    notes: str | None = None
    lost_reason: str | None = None
    product_name: str | None = None
    currency_code: str | None = None
    incoterm_code: str | None = None
    parties: list[PartyOut] = []
    milestones: list[MilestoneOut] = []
    documents: list["DocOut"] = []


class DocOut(ORM):
    id: uuid.UUID
    kind: DocumentKind
    title: str
    original_filename: str | None
    size_bytes: int | None
    created_at: datetime


DealDetail.model_rebuild()
