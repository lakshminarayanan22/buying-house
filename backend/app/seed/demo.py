"""Demo data: a handful of realistic Tiruppur/Erode suppliers and one brand.

Not fixtures for tests — this is for looking at the screens with something plausible on them,
and for sanity-checking that the directory filters behave on data that resembles the real
thing. Idempotent: re-running updates rather than duplicating.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.db import SessionLocal
from app.enums import (
    CapacityUom,
    DataSource,
    OrgStatus,
    OrgType,
    ReferenceDomain,
    Role,
    UserStatus,
    VerificationStatus,
)
from app.models import (
    BrandSupplierReveal,
    Contact,
    Organization,
    SupplierCapability,
    SupplierCapabilityConstruction,
    SupplierCapabilityFibre,
    SupplierCertification,
    SupplierMachine,
    SupplierProcess,
    SupplierProfile,
    User,
)
from app.services import completeness
from app.services.taxonomy import resolve

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("demo")

SUPPLIERS = [
    {
        "name": "Kovai Knits Pvt Ltd",
        "city": "Tiruppur",
        "state": "Tamil Nadu",
        "gst": "33AABCK1234M1Z5",
        "contact": ("R. Murugan", "+919000000101"),
        "status": OrgStatus.VERIFIED,
        "narrative": (
            "Single jersey and pique knitting with in-house stitching. Known for heavy-GSM "
            "french terry and consistent shade matching across large repeat orders for "
            "European high-street buyers."
        ),
        "processes": [
            ("Knitting - circular", 250000, "PCS", 1000, "PCS", 45, 10),
            ("Stitching", 180000, "PCS", 500, "PCS", 40, 12),
        ],
        "capabilities": [
            ("T-shirts", ["Cotton", "Organic cotton"], ["Single Jersey", "Pique"], 140, 220),
            ("Polo shirts", ["Cotton"], ["Pique"], 180, 240),
        ],
        "machines": [("sinker machine", 24), ("overlock", 60), ("flatlock", 30)],
        "certs": [("GOTS", "CU-820145", 400), ("OEKO-TEX Standard 100", "SH-025-2024", 220)],
    },
    {
        "name": "Erode Processors Pvt Ltd",
        "city": "Erode",
        "state": "Tamil Nadu",
        "gst": "33AAECE5678N1Z2",
        "contact": ("S. Kumar", "+919000000102"),
        "status": OrgStatus.VERIFIED,
        "narrative": (
            "Fabric dyeing and finishing house running soft-flow machines, with reactive and "
            "disperse dyeing. Strong on dark shades and reproducible lab dips."
        ),
        "processes": [
            ("Fabric dyeing", 400000, "KG", 500, "KG", 21, 7),
            ("Finishing", 380000, "KG", 500, "KG", 14, 5),
        ],
        "capabilities": [("T-shirts", ["Cotton", "Viscose"], ["Single Jersey", "Interlock"], 120, 320)],
        "machines": [("soft flow", 12), ("stenter", 3), ("compactor", 4)],
        "certs": [("GOTS", "CU-771002", 150), ("ZDHC", "ZD-2025-8891", 300)],
    },
    {
        "name": "Salem Spinners Ltd",
        "city": "Salem",
        "state": "Tamil Nadu",
        "gst": "33AAFCS9012P1Z7",
        "contact": ("A. Raja", "+919000000103"),
        "status": OrgStatus.VERIFIED,
        "narrative": (
            "Ring-spun combed yarn from 20s to 40s counts, including organic and BCI cotton, "
            "supplying knitters across Tiruppur."
        ),
        "processes": [("Spinning", 900000, "KG", 2000, "KG", 30, 14)],
        "capabilities": [("T-shirts", ["Cotton", "Organic cotton", "BCI cotton"], [], 0, 0)],
        "machines": [],
        "certs": [("OCS", "OCS-4471", 260)],
    },
    {
        "name": "Karur Home Textiles",
        "city": "Karur",
        "state": "Tamil Nadu",
        "gst": "33AADCK3456Q1Z9",
        "contact": ("K. Bala", "+919000000104"),
        "status": OrgStatus.SUBMITTED,
        "narrative": (
            "Woven home textiles — bed linen and kitchen linen — with in-house weaving and "
            "made-ups, mainly for European retail programmes."
        ),
        "processes": [
            ("Weaving", 120000, "METRES", 3000, "METRES", 50, 21),
            ("Stitching", 60000, "PCS", 1000, "PCS", 45, 18),
        ],
        "capabilities": [("Bed linen", ["Cotton", "Linen"], ["Plain weave", "Satin"], 110, 200)],
        "machines": [("air jet loom", 48)],
        "certs": [],
    },
    {
        "name": "Coimbatore Garment Works",
        "city": "Coimbatore",
        "state": "Tamil Nadu",
        "gst": "33AAGCC7890R1Z4",
        "contact": ("M. Selvam", "+919000000105"),
        "status": OrgStatus.DRAFT,
        "narrative": "",
        "processes": [("Stitching", 90000, "PCS", 800, "PCS", 42, None)],
        "capabilities": [("Sweatshirts & hoodies", ["Cotton", "Polyester"], ["French Terry"], 240, 380)],
        "machines": [("single needle", 120)],
        "certs": [],
    },
]


def _ref(db: Session, domain: ReferenceDomain, text: str):
    item = resolve(db, domain, text)
    if item is None:
        raise ValueError(f"demo data references unknown {domain} '{text}'")
    return item


def seed_demo(db: Session) -> None:
    india = _ref(db, ReferenceDomain.COUNTRY, "India")

    for spec in SUPPLIERS:
        org = db.scalars(
            select(Organization).where(func.lower(Organization.legal_name) == spec["name"].lower())
        ).first()
        if org is None:
            org = Organization(type=OrgType.SUPPLIER, legal_name=spec["name"])
            db.add(org)
            db.flush()

        org.trade_name = spec["name"]
        org.city = spec["city"]
        org.state = spec["state"]
        org.country_id = india.id
        org.gst_no = spec["gst"]
        org.status = spec["status"]
        org.created_by_internal = True

        profile = db.get(SupplierProfile, org.id) or SupplierProfile(org_id=org.id)
        profile.capability_narrative = spec["narrative"] or None
        profile.source = DataSource.INTERNAL_VERIFIED
        db.add(profile)

        if not db.scalars(select(Contact).where(Contact.org_id == org.id)).first():
            name, phone = spec["contact"]
            db.add(
                Contact(org_id=org.id, name=name, phone=phone, whatsapp=phone, is_primary=True)
            )

        for proc_name, capacity, cap_uom, moq, moq_uom, lead, sample in spec["processes"]:
            item = _ref(db, ReferenceDomain.PROCESS_TYPE, proc_name)
            row = db.scalars(
                select(SupplierProcess).where(
                    SupplierProcess.org_id == org.id,
                    SupplierProcess.process_type_id == item.id,
                )
            ).first() or SupplierProcess(org_id=org.id, process_type_id=item.id)
            row.monthly_capacity_value = capacity
            row.capacity_uom = CapacityUom(cap_uom)
            row.min_order_qty = moq
            row.moq_uom = CapacityUom(moq_uom)
            row.standard_lead_time_days = lead
            row.sample_lead_time_days = sample
            row.source = DataSource.INTERNAL_VERIFIED
            db.add(row)

        for cat_name, fibres, constructions, gsm_min, gsm_max in spec["capabilities"]:
            item = _ref(db, ReferenceDomain.PRODUCT_CATEGORY, cat_name)
            cap = db.scalars(
                select(SupplierCapability).where(
                    SupplierCapability.org_id == org.id,
                    SupplierCapability.product_category_id == item.id,
                )
            ).first() or SupplierCapability(org_id=org.id, product_category_id=item.id)
            cap.gsm_min = gsm_min or None
            cap.gsm_max = gsm_max or None
            cap.source = DataSource.INTERNAL_VERIFIED
            db.add(cap)
            db.flush()

            for fibre_name in fibres:
                fibre = _ref(db, ReferenceDomain.FIBRE, fibre_name)
                if not db.scalars(
                    select(SupplierCapabilityFibre).where(
                        SupplierCapabilityFibre.capability_id == cap.id,
                        SupplierCapabilityFibre.fibre_id == fibre.id,
                    )
                ).first():
                    db.add(SupplierCapabilityFibre(capability_id=cap.id, fibre_id=fibre.id))

            for construction_name in constructions:
                construction = _ref(db, ReferenceDomain.FABRIC_CONSTRUCTION, construction_name)
                if not db.scalars(
                    select(SupplierCapabilityConstruction).where(
                        SupplierCapabilityConstruction.capability_id == cap.id,
                        SupplierCapabilityConstruction.construction_id == construction.id,
                    )
                ).first():
                    db.add(
                        SupplierCapabilityConstruction(
                            capability_id=cap.id, construction_id=construction.id
                        )
                    )

        for machine_name, count in spec["machines"]:
            machine_type = _ref(db, ReferenceDomain.MACHINERY_TYPE, machine_name)
            if not db.scalars(
                select(SupplierMachine).where(
                    SupplierMachine.org_id == org.id,
                    SupplierMachine.machine_type_id == machine_type.id,
                )
            ).first():
                db.add(
                    SupplierMachine(
                        org_id=org.id, machine_type_id=machine_type.id, count=count,
                        source=DataSource.INTERNAL_VERIFIED,
                    )
                )

        for cert_name, number, days_valid in spec["certs"]:
            cert_type = _ref(db, ReferenceDomain.CERTIFICATION, cert_name)
            row = db.scalars(
                select(SupplierCertification).where(
                    SupplierCertification.org_id == org.id,
                    SupplierCertification.certification_id == cert_type.id,
                )
            ).first() or SupplierCertification(
                org_id=org.id, certification_id=cert_type.id, certificate_no=number
            )
            row.issued_on = date.today() - timedelta(days=365)
            row.valid_till = date.today() + timedelta(days=days_valid)
            # Verified on purpose: an unverified certificate satisfies no filter, so demo data
            # that left these PENDING would make the certification facet look broken.
            row.verification_status = VerificationStatus.VERIFIED
            row.source = DataSource.INTERNAL_VERIFIED
            db.add(row)

        db.flush()
        completeness.refresh_supplier(db, org)

    # One brand, plus a login for it, so the identity-redaction behaviour can be seen.
    brand = db.scalars(
        select(Organization).where(Organization.legal_name == "Northwind Apparel Ltd")
    ).first()
    if brand is None:
        brand = Organization(
            type=OrgType.BRAND, legal_name="Northwind Apparel Ltd",
            trade_name="Northwind", city="London", status=OrgStatus.VERIFIED,
        )
        db.add(brand)
        db.flush()

    for email, role, name in [
        ("buyer@northwind.co", Role.BRAND_ADMIN, "Helen Marsh"),
        ("merch@buyinghouse.co", Role.INTERNAL_MERCHANDISER, "Priya Ramesh"),
        ("sourcing@buyinghouse.co", Role.INTERNAL_SOURCING_HEAD, "Anand Iyer"),
    ]:
        if not db.scalars(select(User).where(User.email == email)).first():
            db.add(
                User(
                    org_id=brand.id if role.side.value == "BRAND" else None,
                    role=role, name=name, email=email,
                    password_hash=hash_password("ChangeMe123!"), status=UserStatus.ACTIVE,
                )
            )

    # Reveal exactly one supplier to the brand, so the directory shows both states side by side.
    kovai = db.scalars(
        select(Organization).where(Organization.legal_name == "Kovai Knits Pvt Ltd")
    ).first()
    if kovai and not db.scalars(
        select(BrandSupplierReveal).where(
            BrandSupplierReveal.brand_org_id == brand.id,
            BrandSupplierReveal.supplier_org_id == kovai.id,
        )
    ).first():
        db.add(
            BrandSupplierReveal(
                brand_org_id=brand.id, supplier_org_id=kovai.id, brand_sees_supplier=True,
                reason="Shortlisted for the AW26 knitwear programme",
            )
        )

    db.commit()
    log.info("demo data: %s suppliers, 1 brand, 3 logins (password ChangeMe123!)", len(SUPPLIERS))


def main() -> None:
    db = SessionLocal()
    try:
        seed_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
