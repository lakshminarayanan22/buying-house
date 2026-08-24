"""Organization, invite and contact schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.enums import OrgStatus, OrgType, Role
from app.schemas.common import ORMModel


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    designation: str | None = Field(None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=30)
    whatsapp: str | None = Field(None, max_length=30)
    language_pref: str = "en"
    is_primary: bool = False


class ContactOut(ORMModel):
    id: uuid.UUID
    name: str
    designation: str | None
    email: str | None
    phone: str | None
    whatsapp: str | None
    is_primary: bool


class OrganizationCreate(BaseModel):
    """Internal-side shell creation (§5.1 step 1 / §5.2 assisted onboarding)."""

    type: OrgType
    legal_name: str = Field(min_length=2, max_length=240)
    trade_name: str | None = Field(None, max_length=240)
    country_code: str | None = Field(None, max_length=10)
    state: str | None = Field(None, max_length=120)
    city: str | None = Field(None, max_length=120)
    address: str | None = None
    pincode: str | None = Field(None, max_length=20)
    gst_no: str | None = Field(None, max_length=30)
    pan: str | None = Field(None, max_length=20)
    website: str | None = Field(None, max_length=240)
    primary_contact: ContactIn | None = None


class OrganizationUpdate(BaseModel):
    legal_name: str | None = Field(None, min_length=2, max_length=240)
    trade_name: str | None = Field(None, max_length=240)
    country_code: str | None = Field(None, max_length=10)
    state: str | None = Field(None, max_length=120)
    city: str | None = Field(None, max_length=120)
    address: str | None = None
    pincode: str | None = Field(None, max_length=20)
    gst_no: str | None = Field(None, max_length=30)
    pan: str | None = Field(None, max_length=20)
    iec_code: str | None = Field(None, max_length=30)
    website: str | None = Field(None, max_length=240)
    year_established: int | None = Field(None, ge=1800, le=2100)
    employee_count: int | None = Field(None, ge=0)


class OrganizationOut(ORMModel):
    id: uuid.UUID
    type: OrgType
    legal_name: str
    trade_name: str | None
    country_id: uuid.UUID | None
    state: str | None
    city: str | None
    status: OrgStatus
    website: str | None
    year_established: int | None
    employee_count: int | None
    created_by_internal: bool
    created_at: datetime


class InviteCreate(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=30)
    role: Role
    name: str | None = Field(None, max_length=160)


class InviteOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str | None
    phone: str | None
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    send_count: int


class VerificationDecision(BaseModel):
    """§5.3. NEEDS_INFO carries the specific list, because "incomplete" is not actionable."""

    decision: OrgStatus
    notes: str | None = None
    requested_items: list[str] = []
