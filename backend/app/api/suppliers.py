"""Supplier onboarding and profile management (§5.2).

The design constraint that shapes every endpoint here: a factory owner on a mid-range Android
over patchy 4G will not complete a 60-field form. Tier 1 is eight fields and takes five
minutes. Everything else is incremental, resumable, and either the supplier or one of our
merchandisers can fill it — the same endpoints serve both, with `source` recording which.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_principal
from app.db import get_db
from app.enums import (
    ActivityAction,
    DataSource,
    NotificationChannel,
    OrgStatus,
    OrgType,
    ReferenceDomain,
    SupplierTier,
)
from app.models import (
    Contact,
    Organization,
    ReferenceItem,
    SupplierCapability,
    SupplierCapabilityConstruction,
    SupplierCapabilityFibre,
    SupplierCapacityCalendar,
    SupplierCertification,
    SupplierMachine,
    SupplierProcess,
    SupplierProfile,
    SupplierReference,
)
from app.rbac import Action, Principal, require
from app.schemas.common import Message
from app.schemas.organization import OrganizationOut
from app.schemas.supplier import (
    CapacityMonthIn,
    CertificationOut,
    CompletenessOut,
    SupplierCapabilityIn,
    SupplierCapabilityOut,
    SupplierCertificationIn,
    SupplierMachineIn,
    SupplierNarrativeIn,
    SupplierProcessIn,
    SupplierProcessOut,
    SupplierProfileOut,
    SupplierReferenceIn,
    SupplierTier1Create,
)
from app.services import activity, completeness
from app.services.notifications import EventKey, enqueue
from app.services.taxonomy import resolve, resolve_or_queue

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _resolve_or_400(
    db: Session, domain: ReferenceDomain, code: str, field: str
) -> ReferenceItem:
    item = resolve(db, domain, code)
    if item is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"'{code}' is not a recognised {field}. Pick from the list, or ask us to add it.",
        )
    return item


def _get_supplier_or_404(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None or org.type != OrgType.SUPPLIER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return org


def _source_for(principal: Principal) -> DataSource:
    """Who is entering this?

    A merchandiser filling a profile during a factory visit has seen the machines; the factory
    typing it on their phone has not been checked by anyone. Both are useful, and the agent
    must be able to tell them apart — so provenance is recorded automatically rather than
    depending on someone remembering to set a flag.
    """
    return DataSource.INTERNAL_VERIFIED if principal.is_internal else DataSource.SELF_REPORTED


def _after_profile_write(db: Session, org: Organization, principal: Principal) -> None:
    completeness.refresh_supplier(db, org)
    activity.record(
        db, entity_type="Organization", entity_id=org.id, action=ActivityAction.UPDATE,
        actor=principal, org_id=org.id, summary="Updated supplier profile",
    )


# --------------------------------------------------------------------------- Tier 1
@router.post("/register", response_model=OrganizationOut, status_code=201)
def register_tier1(
    body: SupplierTier1Create,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """§5.2 Tier 1 — Registered. Eight fields, five minutes. This gets a factory *in*.

    Deliberately does not ask for GST, capacity, MOQ, machinery or certificates. Those are
    Tier 2, and asking for them here is how you lose the supplier at field nine.
    """
    require(principal, Action.CREATE, "Organization")

    process = _resolve_or_400(db, ReferenceDomain.PROCESS_TYPE, body.primary_process_code, "process")
    category = _resolve_or_400(
        db, ReferenceDomain.PRODUCT_CATEGORY, body.primary_category_code, "product category"
    )
    country = _resolve_or_400(db, ReferenceDomain.COUNTRY, body.country_code, "country")

    org = Organization(
        type=OrgType.SUPPLIER,
        legal_name=body.factory_name,
        trade_name=body.factory_name,
        city=body.city,
        country_id=country.id,
        status=OrgStatus.DRAFT,
        created_by_internal=principal.is_internal,
        created_by_user_id=principal.user_id,
    )
    db.add(org)
    db.flush()

    db.add_all([
        SupplierProfile(org_id=org.id, source=_source_for(principal)),
        Contact(
            org_id=org.id, name=body.contact_name, phone=body.phone, whatsapp=body.whatsapp,
            language_pref=body.language_pref, is_primary=True,
        ),
        SupplierProcess(
            org_id=org.id, process_type_id=process.id, source=_source_for(principal)
        ),
        SupplierCapability(
            org_id=org.id, product_category_id=category.id, source=_source_for(principal)
        ),
    ])
    db.flush()

    _after_profile_write(db, org, principal)
    activity.record(
        db, entity_type="Organization", entity_id=org.id, action=ActivityAction.CREATE,
        actor=principal, org_id=org.id,
        summary=f"Tier-1 registration: {org.display_name}, {body.city}",
    )
    db.commit()
    db.refresh(org)
    return OrganizationOut.model_validate(org)


# --------------------------------------------------------------------------- profile
@router.get("/{org_id}/profile", response_model=SupplierProfileOut)
def get_profile(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> SupplierProfileOut:
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.VIEW, org)

    profile = db.get(SupplierProfile, org_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return SupplierProfileOut.model_validate(profile)


@router.get("/{org_id}/completeness", response_model=CompletenessOut)
def get_completeness(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CompletenessOut:
    """What is still missing, and what completing it unlocks.

    Shown to the supplier as a progress meter, and used by the nudge campaign — §11: incomplete
    profiles are invisible to the matching engine, so this is not a vanity metric.
    """
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.VIEW, org)
    return CompletenessOut(**completeness.evaluate_supplier(db, org))


@router.put("/{org_id}/narrative", response_model=SupplierProfileOut)
def set_narrative(
    org_id: uuid.UUID,
    body: SupplierNarrativeIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> SupplierProfileOut:
    """The one free-text onboarding answer, captured now for the Phase 6 semantic re-rank."""
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    profile = db.get(SupplierProfile, org_id) or SupplierProfile(org_id=org_id)
    profile.capability_narrative = body.capability_narrative
    profile.narrative_language = body.narrative_language
    db.add(profile)
    _after_profile_write(db, org, principal)
    db.commit()
    db.refresh(profile)
    return SupplierProfileOut.model_validate(profile)


# ------------------------------------------------------------------------- processes
@router.get("/{org_id}/processes", response_model=list[SupplierProcessOut])
def list_processes(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[SupplierProcessOut]:
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.VIEW, org)
    rows = db.scalars(select(SupplierProcess).where(SupplierProcess.org_id == org_id)).all()
    return [SupplierProcessOut.model_validate(r) for r in rows]


@router.put("/{org_id}/processes", response_model=list[SupplierProcessOut])
def upsert_process(
    org_id: uuid.UUID,
    body: SupplierProcessIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[SupplierProcessOut]:
    """Add or update one process. Idempotent on (org, process), so a resumed form is safe."""
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    process_type = _resolve_or_400(
        db, ReferenceDomain.PROCESS_TYPE, body.process_code, "process"
    )
    row = db.scalars(
        select(SupplierProcess).where(
            SupplierProcess.org_id == org_id,
            SupplierProcess.process_type_id == process_type.id,
        )
    ).first()
    if row is None:
        row = SupplierProcess(org_id=org_id, process_type_id=process_type.id)
        db.add(row)

    for field, value in body.model_dump(exclude={"process_code"}).items():
        setattr(row, field, value)
    row.source = _source_for(principal)

    _after_profile_write(db, org, principal)
    db.commit()

    rows = db.scalars(select(SupplierProcess).where(SupplierProcess.org_id == org_id)).all()
    return [SupplierProcessOut.model_validate(r) for r in rows]


@router.delete("/{org_id}/processes/{process_id}", response_model=Message)
def delete_process(
    org_id: uuid.UUID,
    process_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Message:
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.DELETE, org)

    row = db.get(SupplierProcess, process_id)
    if row is None or row.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    db.delete(row)
    db.flush()
    _after_profile_write(db, org, principal)
    db.commit()
    return Message(detail="Process removed")


# ----------------------------------------------------------------------- capabilities
@router.put("/{org_id}/capabilities", response_model=SupplierCapabilityOut)
def upsert_capability(
    org_id: uuid.UUID,
    body: SupplierCapabilityIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> SupplierCapabilityOut:
    """What this factory can make in one product category.

    Unrecognised fibres and constructions are queued for review rather than rejected: a
    supplier must not be blocked mid-form because we have not added "burnout jersey" yet.
    """
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    category = _resolve_or_400(
        db, ReferenceDomain.PRODUCT_CATEGORY, body.category_code, "product category"
    )
    currency = None
    if body.currency_code:
        currency = _resolve_or_400(db, ReferenceDomain.CURRENCY, body.currency_code, "currency")

    row = db.scalars(
        select(SupplierCapability).where(
            SupplierCapability.org_id == org_id,
            SupplierCapability.product_category_id == category.id,
        )
    ).first()
    if row is None:
        row = SupplierCapability(org_id=org_id, product_category_id=category.id)
        db.add(row)
        db.flush()

    row.gsm_min = body.gsm_min
    row.gsm_max = body.gsm_max
    row.size_range = body.size_range
    row.price_band_min = body.price_band_min
    row.price_band_max = body.price_band_max
    row.currency_id = currency.id if currency else None
    row.notes = body.notes
    row.source = _source_for(principal)

    # Replace rather than merge: the form sends the full set, and a stale fibre left behind
    # would make the supplier matchable for work they told us they no longer do.
    for existing in db.scalars(
        select(SupplierCapabilityFibre).where(
            SupplierCapabilityFibre.capability_id == row.id
        )
    ).all():
        db.delete(existing)
    for existing in db.scalars(
        select(SupplierCapabilityConstruction).where(
            SupplierCapabilityConstruction.capability_id == row.id
        )
    ).all():
        db.delete(existing)
    db.flush()

    # Dedupe AFTER resolution, not before: "S/J" and "Sinker" are different strings and the
    # same construction, and a supplier ticking both in a multi-select is the normal case.
    seen_fibres: set[uuid.UUID] = set()
    for code in body.fibre_codes:
        fibre = resolve_or_queue(
            db, ReferenceDomain.FIBRE, code,
            source_entity_type="SupplierCapability", source_entity_id=row.id,
        )
        if fibre is not None and fibre.id not in seen_fibres:
            seen_fibres.add(fibre.id)
            db.add(SupplierCapabilityFibre(capability_id=row.id, fibre_id=fibre.id))

    seen_constructions: set[uuid.UUID] = set()
    for code in body.construction_codes:
        construction = resolve_or_queue(
            db, ReferenceDomain.FABRIC_CONSTRUCTION, code,
            source_entity_type="SupplierCapability", source_entity_id=row.id,
        )
        if construction is not None and construction.id not in seen_constructions:
            seen_constructions.add(construction.id)
            db.add(
                SupplierCapabilityConstruction(
                    capability_id=row.id, construction_id=construction.id
                )
            )

    _after_profile_write(db, org, principal)
    db.commit()
    db.refresh(row)
    return SupplierCapabilityOut.model_validate(row)


@router.get("/{org_id}/capabilities", response_model=list[SupplierCapabilityOut])
def list_capabilities(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[SupplierCapabilityOut]:
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.VIEW, org)
    rows = db.scalars(
        select(SupplierCapability).where(SupplierCapability.org_id == org_id)
    ).all()
    return [SupplierCapabilityOut.model_validate(r) for r in rows]


# --------------------------------------------------------------------------- machines
@router.post("/{org_id}/machines", response_model=Message, status_code=201)
def add_machine(
    org_id: uuid.UUID,
    body: SupplierMachineIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Message:
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    machine_type = _resolve_or_400(
        db, ReferenceDomain.MACHINERY_TYPE, body.machine_type_code, "machine type"
    )
    db.add(
        SupplierMachine(
            org_id=org_id, machine_type_id=machine_type.id, source=_source_for(principal),
            **body.model_dump(exclude={"machine_type_code"}),
        )
    )
    db.flush()
    _after_profile_write(db, org, principal)
    db.commit()
    return Message(detail=f"Added {body.count} x {machine_type.name}")


# --------------------------------------------------------------------- certifications
@router.post("/{org_id}/certifications", response_model=CertificationOut, status_code=201)
def add_certification(
    org_id: uuid.UUID,
    body: SupplierCertificationIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> CertificationOut:
    """Record a certificate. It counts for nothing until a human verifies it (§5.3).

    Left PENDING on purpose: an unverified GOTS claim must not make a supplier eligible for a
    GOTS enquiry, because the whole point of the filter is that the certificate is real.
    """
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    certification = _resolve_or_400(
        db, ReferenceDomain.CERTIFICATION, body.certification_code, "certification"
    )
    if body.issued_on and body.valid_till and body.valid_till < body.issued_on:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="valid_till cannot be before issued_on"
        )

    row = SupplierCertification(
        org_id=org_id, certification_id=certification.id, source=_source_for(principal),
        **body.model_dump(exclude={"certification_code"}),
    )
    db.add(row)
    db.flush()
    _after_profile_write(db, org, principal)
    db.commit()
    db.refresh(row)
    return CertificationOut.model_validate(row)


@router.get("/{org_id}/certifications", response_model=list[CertificationOut])
def list_certifications(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[CertificationOut]:
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.VIEW, org)
    rows = db.scalars(
        select(SupplierCertification).where(SupplierCertification.org_id == org_id)
    ).all()
    return [CertificationOut.model_validate(r) for r in rows]


# --------------------------------------------------------------------------- capacity
@router.put("/{org_id}/capacity", response_model=Message)
def set_capacity_month(
    org_id: uuid.UUID,
    body: CapacityMonthIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Message:
    """Month-wise free capacity. A rough number beats no number (§11)."""
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    process_type = _resolve_or_400(
        db, ReferenceDomain.PROCESS_TYPE, body.process_code, "process"
    )
    month = body.month.replace(day=1)

    row = db.scalars(
        select(SupplierCapacityCalendar).where(
            SupplierCapacityCalendar.org_id == org_id,
            SupplierCapacityCalendar.process_type_id == process_type.id,
            SupplierCapacityCalendar.month == month,
        )
    ).first()
    if row is None:
        row = SupplierCapacityCalendar(
            org_id=org_id, process_type_id=process_type.id, month=month
        )
        db.add(row)

    row.total_qty = body.total_qty
    row.committed_qty = body.committed_qty
    # Derive what was not given, so a supplier who fills in two of three numbers still produces
    # a row the capacity filter can use.
    if body.available_qty is not None:
        row.available_qty = body.available_qty
    elif body.total_qty is not None and body.committed_qty is not None:
        row.available_qty = body.total_qty - body.committed_qty
    row.uom = body.uom
    row.source = _source_for(principal)

    db.commit()
    return Message(detail=f"Capacity recorded for {month.isoformat()[:7]}")


# ------------------------------------------------------------------------ references
@router.post("/{org_id}/references", response_model=Message, status_code=201)
def add_reference(
    org_id: uuid.UUID,
    body: SupplierReferenceIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Message:
    """Past work, so a factory with no history *with us* is not invisible on day one (§10)."""
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.UPDATE, org)

    country = (
        _resolve_or_400(db, ReferenceDomain.COUNTRY, body.buyer_country_code, "country")
        if body.buyer_country_code else None
    )
    category = (
        _resolve_or_400(db, ReferenceDomain.PRODUCT_CATEGORY, body.category_code, "category")
        if body.category_code else None
    )

    db.add(
        SupplierReference(
            org_id=org_id,
            buyer_name=body.buyer_name,
            buyer_country_id=country.id if country else None,
            product_category_id=category.id if category else None,
            annual_qty=body.annual_qty,
            qty_uom=body.qty_uom,
            year=body.year,
            description=body.description,
            is_contactable=body.is_contactable,
        )
    )
    db.flush()
    _after_profile_write(db, org, principal)
    db.commit()
    return Message(detail="Reference added")


# --------------------------------------------------------------------------- submit
@router.post("/{org_id}/submit", response_model=OrganizationOut)
def submit_for_review(
    org_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    """Hand a profile to our team for verification (§5.3 DRAFT -> SUBMITTED)."""
    org = _get_supplier_or_404(db, org_id)
    require(principal, Action.SUBMIT, org)

    result = completeness.evaluate_supplier(db, org)
    if result["tier"] == SupplierTier.TIER_1_REGISTERED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Add capacity, MOQ and lead times before submitting. "
                f"Still missing: {', '.join(result['missing'])}"
            ),
        )

    org.status = OrgStatus.SUBMITTED
    completeness.refresh_supplier(db, org)

    enqueue(
        db, event_key=EventKey.SUPPLIER_PROFILE_SUBMITTED, user=None,
        channels=[NotificationChannel.IN_APP],
        payload={
            "supplier_name": org.display_name,
            "city": org.city or "",
            "completeness_pct": result["completeness_pct"],
            "submitted_on": "today",
            "review_url": f"/internal/suppliers/{org.id}",
        },
        entity_type="Organization", entity_id=org.id,
    )
    activity.record(
        db, entity_type="Organization", entity_id=org.id, action=ActivityAction.STATUS_CHANGE,
        actor=principal, org_id=org.id, summary="Submitted for verification",
        after={"status": OrgStatus.SUBMITTED, "completeness_pct": result["completeness_pct"]},
    )
    db.commit()
    db.refresh(org)
    return OrganizationOut.model_validate(org)
