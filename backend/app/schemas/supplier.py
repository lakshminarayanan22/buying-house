"""Supplier onboarding and profile schemas.

The Tier-1 payload is the §5.2 contract: eight fields, five minutes, nothing optional-looking
that is secretly required. Everything richer is a separate, later call.
"""
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.enums import CapacityUom, DataSource, SupplierTier, VerificationStatus
from app.schemas.common import ORMModel


class SupplierTier1Create(BaseModel):
    """§5.2 Tier 1 — Registered. This gets a factory *in*; nothing else is asked yet.

    Codes rather than ids: the form is filled from a dropdown, but assisted onboarding and the
    Excel importer both arrive with text, and both resolve through the same alias table.
    """

    factory_name: str = Field(min_length=2, max_length=240)
    city: str = Field(min_length=1, max_length=120)
    country_code: str = "IN"
    primary_process_code: str = Field(min_length=1, max_length=60)
    primary_category_code: str = Field(min_length=1, max_length=60)
    contact_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=6, max_length=30)
    whatsapp: str | None = Field(None, max_length=30)
    language_pref: str = "en"

    @model_validator(mode="after")
    def default_whatsapp_to_phone(self) -> "SupplierTier1Create":
        # In practice the WhatsApp number is the phone number. Asking twice loses people.
        if not self.whatsapp:
            object.__setattr__(self, "whatsapp", self.phone)
        return self


class SupplierProcessIn(BaseModel):
    process_code: str = Field(min_length=1, max_length=60)
    is_inhouse: bool = True
    is_subcontracted: bool = False
    subcontractor_notes: str | None = None
    monthly_capacity_value: float | None = Field(None, ge=0)
    capacity_uom: CapacityUom | None = None
    min_order_qty: float | None = Field(None, ge=0)
    moq_uom: CapacityUom | None = None
    standard_lead_time_days: int | None = Field(None, ge=0, le=365)
    sample_lead_time_days: int | None = Field(None, ge=0, le=365)

    @model_validator(mode="after")
    def capacity_requires_uom(self) -> "SupplierProcessIn":
        # A capacity of "120000" with no unit is not data. The database rejects it too; failing
        # here gives the supplier a readable message instead of a 500.
        if self.monthly_capacity_value is not None and self.capacity_uom is None:
            raise ValueError("capacity_uom is required when monthly_capacity_value is given")
        if self.min_order_qty is not None and self.moq_uom is None:
            raise ValueError("moq_uom is required when min_order_qty is given")
        if not self.is_inhouse and not self.is_subcontracted:
            raise ValueError("a process must be in-house, subcontracted, or both")
        return self


class SupplierProcessOut(ORMModel):
    id: uuid.UUID
    process_type_id: uuid.UUID
    is_inhouse: bool
    is_subcontracted: bool
    monthly_capacity_value: float | None
    capacity_uom: CapacityUom | None
    min_order_qty: float | None
    moq_uom: CapacityUom | None
    standard_lead_time_days: int | None
    sample_lead_time_days: int | None
    source: DataSource


class SupplierCapabilityIn(BaseModel):
    category_code: str = Field(min_length=1, max_length=60)
    fibre_codes: list[str] = []
    construction_codes: list[str] = []
    gsm_min: int | None = Field(None, ge=0, le=2000)
    gsm_max: int | None = Field(None, ge=0, le=2000)
    size_range: str | None = Field(None, max_length=160)
    price_band_min: float | None = Field(None, ge=0)
    price_band_max: float | None = Field(None, ge=0)
    currency_code: str | None = Field(None, max_length=10)
    notes: str | None = None

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> "SupplierCapabilityIn":
        if self.gsm_min is not None and self.gsm_max is not None and self.gsm_min > self.gsm_max:
            raise ValueError("gsm_min cannot exceed gsm_max")
        if (
            self.price_band_min is not None
            and self.price_band_max is not None
            and self.price_band_min > self.price_band_max
        ):
            raise ValueError("price_band_min cannot exceed price_band_max")
        if (self.price_band_min is not None or self.price_band_max is not None) \
                and not self.currency_code:
            raise ValueError("currency_code is required when a price band is given")
        return self


class SupplierCapabilityOut(ORMModel):
    id: uuid.UUID
    product_category_id: uuid.UUID
    gsm_min: int | None
    gsm_max: int | None
    size_range: str | None
    price_band_min: float | None
    price_band_max: float | None
    currency_id: uuid.UUID | None
    notes: str | None
    source: DataSource


class SupplierMachineIn(BaseModel):
    machine_type_code: str = Field(min_length=1, max_length=60)
    make: str | None = Field(None, max_length=120)
    model: str | None = Field(None, max_length=120)
    count: int = Field(1, ge=1, le=10000)
    gauge: str | None = Field(None, max_length=40)
    diameter: str | None = Field(None, max_length=40)
    year_of_make: int | None = Field(None, ge=1950, le=2100)
    condition: str | None = Field(None, max_length=40)


class SupplierCertificationIn(BaseModel):
    certification_code: str = Field(min_length=1, max_length=60)
    certificate_no: str | None = Field(None, max_length=120)
    issuing_body: str | None = Field(None, max_length=200)
    scope: str | None = None
    issued_on: date | None = None
    valid_till: date | None = None
    document_id: uuid.UUID | None = None


class SupplierReferenceIn(BaseModel):
    """Past work, asked at onboarding purely so a new factory is not invisible on day one."""

    buyer_name: str | None = Field(None, max_length=200)
    buyer_country_code: str | None = Field(None, max_length=10)
    category_code: str | None = Field(None, max_length=60)
    annual_qty: float | None = Field(None, ge=0)
    qty_uom: CapacityUom | None = None
    year: int | None = Field(None, ge=1980, le=2100)
    description: str | None = None
    is_contactable: bool = False


class SupplierNarrativeIn(BaseModel):
    """The one deliberately unstructured onboarding answer.

    Everything else is forced into the taxonomy because free text is unmatchable. This field is
    the exception, and it exists for a specific downstream job: it is what gets embedded for
    the Phase 6 semantic re-rank, which catches the nuance the structured fields miss
    ("heavy-GSM french terry with reactive dyeing"). It never bypasses a hard filter.
    """

    capability_narrative: str = Field(min_length=20, max_length=4000)
    narrative_language: str = "en"


class SupplierProfileOut(ORMModel):
    org_id: uuid.UUID
    completeness_tier: SupplierTier
    completeness_pct: int
    export_experience_years: int | None
    annual_turnover_band: str | None
    is_vertically_integrated: bool
    capability_narrative: str | None
    source: DataSource


class CompletenessOut(BaseModel):
    completeness_pct: int
    tier: SupplierTier
    missing: list[str]
    checks: dict[str, bool]


class CapacityMonthIn(BaseModel):
    """§11: even a rough month-wise availability slider is enough to start."""

    process_code: str = Field(min_length=1, max_length=60)
    month: date
    total_qty: float | None = Field(None, ge=0)
    committed_qty: float | None = Field(None, ge=0)
    available_qty: float | None = Field(None, ge=0)
    uom: CapacityUom | None = None


class CertificationOut(ORMModel):
    id: uuid.UUID
    certification_id: uuid.UUID
    certificate_no: str | None
    issuing_body: str | None
    issued_on: date | None
    valid_till: date | None
    verification_status: VerificationStatus
    source: DataSource
