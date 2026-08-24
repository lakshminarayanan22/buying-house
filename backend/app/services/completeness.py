"""Profile completeness and tier promotion (§5.2).

§11: incomplete profiles are invisible to the matching engine. The percentage is not a
decoration — it drives the nudge campaign, and the tier gates what a supplier can participate
in. Weights are deliberately blunt; what matters is that the fields the agent needs are the
fields that move the number.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import SupplierTier, VerificationStatus
from app.models import (
    Contact,
    Document,
    Organization,
    SupplierCapability,
    SupplierCertification,
    SupplierMachine,
    SupplierProcess,
    SupplierProfile,
)

# (name, weight, tier, gates_tier)
#
# Two different jobs, deliberately separated:
#
#   weight     contributes to the completeness percentage the supplier sees and the nudge
#              campaign chases.
#   gates_tier decides whether the supplier is promoted into that tier at all.
#
# Only the checks that decide *matchability* gate a tier — the fields §10 step 2 filters on.
# A factory photo and a GST number matter, and they move the percentage, but blocking a fully
# specified factory from RFQ participation because nobody uploaded a photo is precisely the
# supplier-adoption failure §11 warns about.
_SUPPLIER_CHECKS = [
    ("identity", 8, SupplierTier.TIER_1_REGISTERED, True),
    ("location", 6, SupplierTier.TIER_1_REGISTERED, True),
    ("contact", 8, SupplierTier.TIER_1_REGISTERED, True),
    ("primary_process", 8, SupplierTier.TIER_1_REGISTERED, True),
    ("primary_category", 6, SupplierTier.TIER_1_REGISTERED, True),
    ("unit_photo", 4, SupplierTier.TIER_1_REGISTERED, False),
    ("process_capacity", 12, SupplierTier.TIER_2_PROFILED, True),
    ("process_moq", 8, SupplierTier.TIER_2_PROFILED, True),
    ("lead_times", 6, SupplierTier.TIER_2_PROFILED, True),
    ("capability_detail", 10, SupplierTier.TIER_2_PROFILED, True),
    ("machinery", 6, SupplierTier.TIER_2_PROFILED, False),
    ("tax_identity", 6, SupplierTier.TIER_2_PROFILED, False),
    ("certifications", 6, SupplierTier.TIER_3_VERIFIED, False),
    ("compliance_or_references", 6, SupplierTier.TIER_3_VERIFIED, False),
]

_TIER_THRESHOLDS = {
    # A tier is reached when every *gating* check belonging to it and all lower tiers passes.
    SupplierTier.TIER_1_REGISTERED: [SupplierTier.TIER_1_REGISTERED],
    SupplierTier.TIER_2_PROFILED: [SupplierTier.TIER_1_REGISTERED, SupplierTier.TIER_2_PROFILED],
}


def evaluate_supplier(db: Session, org: Organization) -> dict:
    """Return which checks pass, the weighted percentage, and the tier earned."""
    org_id = org.id

    processes = db.scalars(select(SupplierProcess).where(SupplierProcess.org_id == org_id)).all()
    capabilities = db.scalars(
        select(SupplierCapability).where(SupplierCapability.org_id == org_id)
    ).all()

    machine_count = db.scalar(
        select(func.count(SupplierMachine.id)).where(SupplierMachine.org_id == org_id)
    ) or 0
    contact_count = db.scalar(
        select(func.count(Contact.id)).where(Contact.org_id == org_id)
    ) or 0
    photo_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.org_id == org_id,
            Document.doc_type.in_(["UNIT_PHOTO", "FACTORY_PHOTO"]),
        )
    ) or 0
    cert_count = db.scalar(
        select(func.count(SupplierCertification.id)).where(
            SupplierCertification.org_id == org_id,
            SupplierCertification.verification_status != VerificationStatus.REJECTED,
        )
    ) or 0

    from app.models import SupplierCompliance, SupplierReference

    other_evidence = (
        db.scalar(select(func.count(SupplierCompliance.id)).where(
            SupplierCompliance.org_id == org_id)) or 0
    ) + (
        db.scalar(select(func.count(SupplierReference.id)).where(
            SupplierReference.org_id == org_id)) or 0
    )

    results = {
        "identity": bool(org.legal_name),
        "location": bool(org.city and org.country_id),
        "contact": contact_count > 0,
        "primary_process": len(processes) > 0,
        "primary_category": len(capabilities) > 0,
        "unit_photo": photo_count > 0,
        # Capacity and MOQ are per-process: one process with a number and three without is not
        # a profile the matcher can filter on.
        "process_capacity": bool(processes) and all(
            p.monthly_capacity_value is not None for p in processes
        ),
        "process_moq": bool(processes) and all(p.min_order_qty is not None for p in processes),
        "lead_times": bool(processes) and all(
            p.standard_lead_time_days is not None for p in processes
        ),
        "capability_detail": bool(capabilities) and all(
            c.fibres and (c.gsm_min is not None or c.gsm_max is not None) for c in capabilities
        ),
        "machinery": machine_count > 0,
        "tax_identity": bool(org.gst_no or org.pan),
        "certifications": cert_count > 0,
        "compliance_or_references": other_evidence > 0,
    }

    earned = sum(weight for name, weight, _, _ in _SUPPLIER_CHECKS if results.get(name))
    total = sum(weight for _, weight, _, _ in _SUPPLIER_CHECKS)
    pct = round(earned * 100 / total) if total else 0

    tier = SupplierTier.TIER_1_REGISTERED
    for candidate in (SupplierTier.TIER_2_PROFILED, SupplierTier.TIER_1_REGISTERED):
        required = _TIER_THRESHOLDS[candidate]
        if all(
            results.get(name)
            for name, _, check_tier, gates in _SUPPLIER_CHECKS
            if gates and check_tier in required
        ):
            tier = candidate
            break

    # TIER_3 is not earned by filling fields — it is granted by a human verification decision
    # (§5.3), so completeness can never promote a supplier into brand-facing status.
    if org.is_verified and tier == SupplierTier.TIER_2_PROFILED:
        tier = SupplierTier.TIER_3_VERIFIED

    missing = [name for name, _, _, _ in _SUPPLIER_CHECKS if not results.get(name)]
    return {"checks": results, "completeness_pct": pct, "tier": tier, "missing": missing}


def refresh_supplier(db: Session, org: Organization) -> SupplierProfile:
    """Recompute and persist completeness. Call after any profile write."""
    profile = db.get(SupplierProfile, org.id)
    if profile is None:
        profile = SupplierProfile(org_id=org.id)
        db.add(profile)

    result = evaluate_supplier(db, org)
    profile.completeness_pct = result["completeness_pct"]
    profile.completeness_tier = result["tier"]
    return profile
