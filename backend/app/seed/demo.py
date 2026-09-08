"""Demo data: Ecolink's two actual deals.

Both are real cases from the business, and they are here because between them they exercise
everything the schema has to handle — a company that is a buyer on one deal, an input supplier
who is nobody's factory, a percentage commission and a margin, and a chain that is two parties
long in one case and three in the other.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.db import SessionLocal
from app.enums import (
    CommissionBasis,
    CommissionStatus,
    CompanyStatus,
    DealRole,
    DealStatus,
    MilestoneStatus,
    ReferenceDomain as D,
    UserRole,
)
from app.models import (
    Company,
    CompanyCertification,
    CompanyClient,
    CompanyProcess,
    CompanyProduct,
    Contact,
    Deal,
    DealMilestone,
    DealParty,
    User,
)
from app.seed.taxonomy import resolve, seed_taxonomy
from app.services import deals as svc

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("demo")


def _ref(db: Session, domain: D, text: str):
    item = resolve(db, domain, text)
    if item is None:
        raise SystemExit(f"{domain} {text!r} is not in the taxonomy")
    return item


def _company(db: Session, name: str, **kw) -> Company:
    existing = db.scalars(select(Company).where(Company.name == name)).first()
    if existing:
        return existing
    company = Company(name=name, **kw)
    db.add(company)
    db.flush()
    return company


def seed_demo(db: Session) -> None:
    seed_taxonomy(db)

    user = db.scalars(select(User).where(User.email == "ops@ecolink.example")).first()
    if user is None:
        user = User(name="Ecolink Ops", email="ops@ecolink.example", role=UserRole.ADMIN,
                    password_hash=hash_password("ChangeMe123!"))
        db.add(user)
        db.flush()

    if db.scalars(select(Deal)).first() is not None:
        log.info("demo deals already present")
        return

    au, inn, jp = (_ref(db, D.COUNTRY, c) for c in ("Australia", "India", "Japan"))
    usd = _ref(db, D.CURRENCY, "USD")

    # ---------------------------------------------------------------- companies
    farm = _company(
        db, "Darling Downs Cotton Growers", legal_name="Darling Downs Cotton Co-operative Ltd",
        country_id=au.id, city="Dalby", sells=True, status=CompanyStatus.ACTIVE,
        capacity_notes="Roughly 9,000 MT of lint a season across the co-operative.",
        notes="Introduced through the Australian cotton growers' association.",
    )
    mill = _company(
        db, "Sri Vaari Spinning Mills", legal_name="Sri Vaari Spinning Mills Pvt Ltd",
        country_id=inn.id, city="Coimbatore",
        # The point of the whole redesign: this company BUYS our cotton and SELLS yarn.
        buys=True, sells=True, status=CompanyStatus.ACTIVE,
        capacity_notes="52,000 spindles. About 900 MT of combed yarn a month.",
        machinery_notes="Rieter and LMW ring frames; 2 blow rooms; auto-coners.",
        moq_notes="Minimum 20 MT per count for a fresh order.",
        payment_terms="30 days from bill of lading",
    )
    jptech = _company(
        db, "Kaimei Cooling Technologies", legal_name="Kaimei Cooling Technologies K.K.",
        country_id=jp.id, city="Osaka", sells=True, status=CompanyStatus.ACTIVE,
        notes="Supplies the cooling finish chemistry and licenses the application method.",
    )
    dyer = _company(
        db, "Erode Processors", legal_name="Erode Processors Pvt Ltd",
        country_id=inn.id, city="Erode", sells=True, status=CompanyStatus.ACTIVE,
        capacity_notes="About 12 MT of knitted fabric a day across soft-flow machines.",
        machinery_notes="12 soft-flow dyeing machines, 3 stenters, 4 compactors.",
        moq_notes="500 kg per shade.",
        lead_time_notes="21 days for dyeing and finishing.",
    )
    brand = _company(
        db, "Northwind Apparel", legal_name="Northwind Apparel Ltd",
        country_id=_ref(db, D.COUNTRY, "United Kingdom").id, city="London",
        buys=True, sells=False, status=CompanyStatus.ACTIVE,
        payment_terms="60 days from delivery, LC at sight for first order",
        quality_requirements="AQL 2.5. Shade continuity across the run. OEKO-TEX on all fabric.",
    )

    db.add_all([
        Contact(company_id=farm.id, name="Alan Prentice", designation="Export manager",
                email="alan@ddcotton.example", phone="+61 400 000 111", is_primary=True),
        Contact(company_id=mill.id, name="R. Senthilkumar", designation="Purchase head",
                phone="+91 90000 00201", whatsapp="+91 90000 00201", is_primary=True),
        Contact(company_id=jptech.id, name="Hiro Tanaka", designation="Business development",
                email="tanaka@kaimei.example", is_primary=True),
        Contact(company_id=dyer.id, name="S. Kumar", designation="Managing partner",
                phone="+91 90000 00102", whatsapp="+91 90000 00102", is_primary=True),
        Contact(company_id=brand.id, name="Helen Marsh", designation="Sourcing manager",
                email="helen@northwind.example", is_primary=True),
    ])

    for company, processes in [
        (farm, ["Cotton growing", "Ginning"]),
        (mill, ["Spinning"]),
        (jptech, ["Chemical / treatment supply"]),
        (dyer, ["Fabric dyeing", "Finishing"]),
    ]:
        for name in processes:
            db.add(CompanyProcess(company_id=company.id, process_id=_ref(db, D.PROCESS, name).id))

    for company, products in [
        (farm, ["Raw cotton"]), (mill, ["Yarn"]),
        (jptech, ["Chemicals & treatments"]), (dyer, ["Finished fabric"]),
        (brand, ["T-shirts", "Polo shirts"]),
    ]:
        for name in products:
            db.add(CompanyProduct(company_id=company.id, product_id=_ref(db, D.PRODUCT, name).id))

    for company, certs in [
        (farm, ["myBMP", "BCI"]), (mill, ["OEKO-TEX Standard 100", "ISO 9001"]),
        (dyer, ["GOTS", "OEKO-TEX Standard 100", "ZDHC"]),
    ]:
        for name in certs:
            db.add(CompanyCertification(
                company_id=company.id, certification_id=_ref(db, D.CERTIFICATION, name).id
            ))

    db.add_all([
        CompanyClient(company_id=dyer.id, client_name="Decathlon", is_current=True),
        CompanyClient(company_id=dyer.id, client_name="Marks & Spencer", is_current=False),
        CompanyClient(company_id=mill.id, client_name="Arvind Ltd", is_current=True),
    ])
    db.flush()

    # ------------------------------------------------- deal 1: Australian cotton -> Indian mill
    cotton = Deal(
        deal_no=svc.next_deal_no(db),
        title="Australian cotton — 240 MT to Sri Vaari",
        description=(
            "Darling Downs supplies 240 MT of lint FOB Brisbane. Sri Vaari buys through us; "
            "we take a commission on the shipped value."
        ),
        product_id=_ref(db, D.PRODUCT, "Raw cotton").id,
        currency_id=usd.id,
        incoterm_id=_ref(db, D.INCOTERM, "FOB").id,
        status=DealStatus.IN_PROGRESS,
        target_ship_date=date.today() + timedelta(days=5),
        owner_user_id=user.id,
    )
    db.add(cotton)
    db.flush()

    grower_leg = DealParty(
        deal_id=cotton.id, company_id=farm.id, role=DealRole.SUPPLIER, sequence=1,
        process_id=_ref(db, D.PROCESS, "Cotton growing").id,
        qty=240, uom="MT", unit_price=1850, value=444000,
        commission_basis=CommissionBasis.PERCENTAGE, commission_pct=1.5,
        commission_status=CommissionStatus.INVOICED,
        invoiced_on=date.today() - timedelta(days=9),
        ship_date=date.today() + timedelta(days=5),
    )
    mill_leg = DealParty(
        deal_id=cotton.id, company_id=mill.id, role=DealRole.BUYER, sequence=2,
        qty=240, uom="MT", value=444000, commission_basis=CommissionBasis.NONE,
    )
    for leg in (grower_leg, mill_leg):
        svc.refresh_commission(leg)
    db.add_all([grower_leg, mill_leg])
    for m, offset, status in [
        ("Contract signed", -30, MilestoneStatus.DONE),
        ("Bales pressed and lot numbers issued", -12, MilestoneStatus.DONE),
        ("Container booked", -4, MilestoneStatus.DONE),
        ("Vessel sails from Brisbane", 5, MilestoneStatus.IN_PROGRESS),
        ("Documents to mill", 8, MilestoneStatus.PENDING),
        ("Commission received", 25, MilestoneStatus.PENDING),
    ]:
        db.add(DealMilestone(
            deal_id=cotton.id, name=m, sequence=len(m),
            planned_date=date.today() + timedelta(days=offset), status=status,
            actual_date=date.today() + timedelta(days=offset)
            if status == MilestoneStatus.DONE else None,
            owner_user_id=user.id,
        ))

    # ------------------------------- deal 2: Japanese cooling finish -> Tiruppur -> brand
    cooling = Deal(
        deal_no=svc.next_deal_no(db),
        title="Kaimei cooling finish — fabric programme for Northwind",
        description=(
            "Kaimei ships the cooling chemistry to Erode, who dye and finish knitted fabric to "
            "it. We market the finished fabric to Northwind at a margin over the processed cost."
        ),
        product_id=_ref(db, D.PRODUCT, "Finished fabric").id,
        currency_id=usd.id,
        status=DealStatus.NEGOTIATING,
        target_ship_date=date.today() + timedelta(days=70),
        owner_user_id=user.id,
    )
    db.add(cooling)
    db.flush()

    cooling_legs = [
        DealParty(
            deal_id=cooling.id, company_id=jptech.id, role=DealRole.INPUT_SUPPLIER, sequence=1,
            process_id=_ref(db, D.PROCESS, "Chemical / treatment supply").id,
            qty=400, uom="LTR", unit_price=42, value=16800,
            commission_basis=CommissionBasis.NONE,
            notes="Chemistry shipped direct to Erode. Kaimei invoices us, we recover in the fabric price.",
        ),
        DealParty(
            deal_id=cooling.id, company_id=dyer.id, role=DealRole.PROCESSOR, sequence=2,
            process_id=_ref(db, D.PROCESS, "Fabric dyeing").id,
            qty=18000, uom="KG", unit_price=2.90, value=52200,
            commission_basis=CommissionBasis.PERCENTAGE, commission_pct=4,
            commission_status=CommissionStatus.DUE,
            ship_date=date.today() + timedelta(days=60),
        ),
        # The margin leg: we buy the finished fabric in at 5.05 and sell it on at 5.60.
        DealParty(
            deal_id=cooling.id, company_id=brand.id, role=DealRole.BUYER, sequence=3,
            qty=18000, uom="KG", unit_price=5.05, resale_unit_price=5.60, value=100800,
            commission_basis=CommissionBasis.MARGIN,
            commission_status=CommissionStatus.NOT_DUE,
            ship_date=date.today() + timedelta(days=70),
        ),
    ]
    for leg in cooling_legs:
        svc.refresh_commission(leg)
    db.add_all(cooling_legs)
    for m, offset, status in [
        ("Cooling finish sample approved by Northwind", -6, MilestoneStatus.DONE),
        ("Price confirmed with Erode", 3, MilestoneStatus.IN_PROGRESS),
        ("Chemistry shipped from Osaka", 14, MilestoneStatus.PENDING),
        ("Bulk dyeing starts", 32, MilestoneStatus.PENDING),
        ("Fabric ex-Erode", 60, MilestoneStatus.PENDING),
    ]:
        db.add(DealMilestone(
            deal_id=cooling.id, name=m, sequence=len(m),
            planned_date=date.today() + timedelta(days=offset), status=status,
            actual_date=date.today() + timedelta(days=offset)
            if status == MilestoneStatus.DONE else None,
            owner_user_id=user.id,
        ))

    db.flush()

    # The cotton deal was worked on this week; the cooling deal has been sitting for three.
    cotton.last_activity_at = datetime.now(timezone.utc) - timedelta(days=1)
    cooling.last_activity_at = datetime.now(timezone.utc) - timedelta(days=23)

    db.commit()
    log.info("seeded %s companies and %s deals (login: ops@ecolink.example / ChangeMe123!)",
         db.scalar(select(func.count(Company.id))), db.scalar(select(func.count(Deal.id))))


def main() -> None:
    db = SessionLocal()
    try:
        seed_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
