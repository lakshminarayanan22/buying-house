"""The simplified schema, tested against how Ecolink actually trades."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import app.models as m
from app.enums import (
    CommissionBasis,
    CommissionStatus,
    DealRole,
    DealStatus,
    MilestoneStatus,
    ReferenceDomain as D,
)
from app.seed.taxonomy import resolve
from app.services import deals as svc


def company(db, name, **kw):
    c = m.Company(name=name, **kw)
    db.add(c)
    db.commit()
    return c


def deal(db, title="Test deal", **kw):
    d = m.Deal(deal_no=svc.next_deal_no(db), title=title, **kw)
    db.add(d)
    db.commit()
    return d


def ref(db, domain, text):
    item = resolve(db, domain, text)
    assert item is not None, f"{text!r} missing from {domain}"
    return item


# ------------------------------------------------- the reason for the redesign
def test_one_company_is_a_buyer_on_one_deal_and_a_supplier_on_another(db, taxonomy):
    """A spinning mill buys our Australian cotton and sells its yarn onward. Typing the company
    as BRAND or SUPPLIER made that impossible to record; role belongs to the deal."""
    mill = company(db, "Sri Vaari Spinning Mills", city="Coimbatore", buys=True, sells=True)
    grower = company(db, "Darling Downs Cotton", city="Dalby")
    weaver = company(db, "Karur Weaving", city="Karur", buys=True)

    cotton = deal(db, "Cotton to the mill")
    yarn = deal(db, "Yarn from the mill")
    db.add_all([
        m.DealParty(deal_id=cotton.id, company_id=grower.id, role=DealRole.SUPPLIER),
        m.DealParty(deal_id=cotton.id, company_id=mill.id, role=DealRole.BUYER),
        m.DealParty(deal_id=yarn.id, company_id=mill.id, role=DealRole.SUPPLIER),
        m.DealParty(deal_id=yarn.id, company_id=weaver.id, role=DealRole.BUYER),
    ])
    db.commit()

    roles = db.scalars(
        select(m.DealParty.role).where(m.DealParty.company_id == mill.id)
    ).all()
    assert sorted(roles) == ["BUYER", "SUPPLIER"]


def test_a_company_may_hold_two_roles_in_one_deal_but_not_the_same_twice(db, taxonomy):
    mill = company(db, "Sri Vaari Spinning Mills", city="Coimbatore")
    d = deal(db)
    db.add(m.DealParty(deal_id=d.id, company_id=mill.id, role=DealRole.SUPPLIER))
    db.commit()
    db.add(m.DealParty(deal_id=d.id, company_id=mill.id, role=DealRole.PROCESSOR))
    db.commit()   # a different role on the same deal is legitimate

    db.add(m.DealParty(deal_id=d.id, company_id=mill.id, role=DealRole.SUPPLIER))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --------------------------------------------------------- the two real deals
def test_the_cotton_trade(db, taxonomy):
    """Australian grower to Indian mill, commission on the shipped value."""
    grower = company(db, "Darling Downs Cotton", city="Dalby")
    mill = company(db, "Sri Vaari Spinning Mills", city="Coimbatore", buys=True)
    d = deal(db, "Australian cotton — 240 MT", status=DealStatus.IN_PROGRESS)

    leg = m.DealParty(
        deal_id=d.id, company_id=grower.id, role=DealRole.SUPPLIER,
        process_id=ref(db, D.PROCESS, "Cotton growing").id,
        qty=240, uom="MT", unit_price=1850, value=444000,
        commission_basis=CommissionBasis.PERCENTAGE, commission_pct=1.5,
    )
    db.add_all([leg, m.DealParty(deal_id=d.id, company_id=mill.id, role=DealRole.BUYER)])
    db.commit()

    svc.refresh_commission(leg)
    assert leg.commission_amount == 6660.0        # 1.5% of 444,000


def test_the_cooling_finish_deal_carries_two_commission_bases(db, taxonomy):
    """Japanese chemistry, an Indian dye house and a brand — a percentage and a margin on one
    deal, which is why commission sits on the party and not on the deal."""
    kaimei = company(db, "Kaimei Cooling Technologies", city="Osaka")
    dyer = company(db, "Erode Processors", city="Erode")
    brand = company(db, "Northwind Apparel", city="London", buys=True, sells=False)
    d = deal(db, "Cooling finish programme")

    chemistry = m.DealParty(
        deal_id=d.id, company_id=kaimei.id, role=DealRole.INPUT_SUPPLIER, sequence=1,
        process_id=ref(db, D.PROCESS, "Chemical / treatment supply").id,
        qty=400, uom="LTR", unit_price=42, value=16800,
        commission_basis=CommissionBasis.NONE,
    )
    dyeing = m.DealParty(
        deal_id=d.id, company_id=dyer.id, role=DealRole.PROCESSOR, sequence=2,
        qty=18000, uom="KG", unit_price=2.90, value=52200,
        commission_basis=CommissionBasis.PERCENTAGE, commission_pct=4,
    )
    sale = m.DealParty(
        deal_id=d.id, company_id=brand.id, role=DealRole.BUYER, sequence=3,
        qty=18000, uom="KG", unit_price=5.05, resale_unit_price=5.60, value=100800,
        commission_basis=CommissionBasis.MARGIN,
    )
    db.add_all([chemistry, dyeing, sale])
    db.commit()

    for p in (chemistry, dyeing, sale):
        svc.refresh_commission(p)
    db.commit()
    db.refresh(d)

    assert dyeing.commission_amount == 2088.0      # 4% of 52,200
    assert sale.commission_amount == 9900.0        # 0.55 x 18,000
    assert d.commission_total == 11988.0


# ------------------------------------------------------------------ constraints
def test_a_margin_cannot_be_negative(db, taxonomy):
    c = company(db, "Erode Processors", city="Erode")
    d = deal(db)
    db.add(m.DealParty(deal_id=d.id, company_id=c.id, role=DealRole.PROCESSOR,
                       qty=100, unit_price=5.00, resale_unit_price=4.50,
                       commission_basis=CommissionBasis.MARGIN))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cannot_invoice_a_commission_with_no_amount(db, taxonomy):
    """This caught a real ordering bug in the demo seed, which marked a leg invoiced before the
    amount had been computed."""
    c = company(db, "Darling Downs Cotton", city="Dalby")
    d = deal(db)
    db.add(m.DealParty(deal_id=d.id, company_id=c.id, role=DealRole.SUPPLIER,
                       commission_basis=CommissionBasis.NONE,
                       commission_status=CommissionStatus.INVOICED))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_percentage_basis_needs_a_percentage(db, taxonomy):
    c = company(db, "Darling Downs Cotton", city="Dalby")
    d = deal(db)
    db.add(m.DealParty(deal_id=d.id, company_id=c.id, role=DealRole.SUPPLIER,
                       commission_basis=CommissionBasis.PERCENTAGE))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_lost_deal_needs_a_reason(db, taxonomy):
    d = m.Deal(deal_no=svc.next_deal_no(db), title="Lost one", status=DealStatus.LOST)
    db.add(d)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_completed_milestone_needs_a_date(db, taxonomy):
    d = deal(db)
    db.add(m.DealMilestone(deal_id=d.id, name="Contract signed", status=MilestoneStatus.DONE))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_document_must_belong_to_a_deal_or_a_company(db, taxonomy):
    db.add(m.Document(title="Orphan", storage_key="k/1"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_documents_group_into_a_folder_per_deal(db, taxonomy):
    c = company(db, "Erode Processors", city="Erode")
    d = deal(db)
    db.add_all([
        m.Document(deal_id=d.id, title="PO 4471", storage_key="k/1", kind="PURCHASE_ORDER"),
        m.Document(deal_id=d.id, title="Invoice 88", storage_key="k/2", kind="INVOICE"),
        m.Document(company_id=c.id, title="Factory brochure", storage_key="k/3", kind="BROCHURE"),
    ])
    db.commit()

    folder = db.scalars(select(m.Document).where(m.Document.deal_id == d.id)).all()
    assert len(folder) == 2
    brochure = db.scalars(
        select(m.Document).where(m.Document.company_id == c.id, m.Document.kind == "BROCHURE")
    ).first()
    assert brochure.title == "Factory brochure"


# -------------------------------------------------------------------- taxonomy
@pytest.mark.parametrize("text,code", [
    ("cotton grower", "COTTON_GROWING"), ("ginner", "GINNING"), ("spinning mill", "SPINNING"),
    ("process house", "FABRIC_DYEING"), ("cooling tech", "CHEMICAL_SUPPLY"),
    ("cmt", "GARMENTING"), ("sourcing agent", "TRADING"),
])
def test_the_words_people_type_resolve(db, taxonomy, text, code):
    assert resolve(db, D.PROCESS, text).code == code


def test_the_taxonomy_reaches_beyond_apparel(db, taxonomy):
    for text in ["australian cotton", "yarn", "auxiliaries", "innerwear"]:
        assert resolve(db, D.PRODUCT, text) is not None, text


# ------------------------------------------------------------- the three screens
@pytest.fixture()
def loaded(db, taxonomy):
    grower = company(db, "Darling Downs Cotton", city="Dalby")
    dyer = company(db, "Erode Processors", city="Erode")
    live = deal(db, "Cotton shipment", status=DealStatus.IN_PROGRESS)
    quiet = deal(db, "Cooling programme", status=DealStatus.NEGOTIATING)
    live.last_activity_at = datetime.now(timezone.utc) - timedelta(days=1)
    quiet.last_activity_at = datetime.now(timezone.utc) - timedelta(days=23)
    db.add_all([
        m.DealParty(deal_id=live.id, company_id=grower.id, role=DealRole.SUPPLIER,
                    value=444000, commission_basis=CommissionBasis.PERCENTAGE,
                    commission_pct=1.5, commission_amount=6660,
                    commission_status=CommissionStatus.INVOICED,
                    invoiced_on=date.today() - timedelta(days=9),
                    ship_date=date.today() + timedelta(days=3)),
        m.DealParty(deal_id=quiet.id, company_id=dyer.id, role=DealRole.PROCESSOR,
                    value=52200, commission_basis=CommissionBasis.PERCENTAGE,
                    commission_pct=4, commission_amount=2088,
                    commission_status=CommissionStatus.DUE,
                    ship_date=date.today() - timedelta(days=2)),
    ])
    db.commit()
    return live, quiet


def test_shipping_soon_includes_the_overdue(db, loaded):
    rows = svc.shipping_soon(db, within_days=7)
    assert len(rows) == 2
    overdue = [r for r in rows if r["overdue"]]
    assert len(overdue) == 1 and overdue[0]["days_out"] == -2


def test_commission_owed_groups_by_who_we_chase(db, loaded):
    owed = svc.commission_owed(db)
    assert owed["outstanding"] == 8748.0
    assert owed["received"] == 0.0
    top = owed["by_company"][0]
    assert top["company"] == "Darling Downs Cotton"
    assert top["days_outstanding"] == 9


def test_gone_quiet_finds_only_the_neglected_deal(db, loaded):
    rows = svc.gone_quiet(db, silent_for_days=14)
    assert [r["title"] for r in rows] == ["Cooling programme"]
    assert rows[0]["days_silent"] >= 22


def test_touching_a_deal_takes_it_off_the_quiet_list(db, loaded):
    _live, quiet = loaded
    assert svc.gone_quiet(db, silent_for_days=14)
    svc.touch(db, quiet, summary="Called Kaimei about pricing")
    db.commit()
    assert svc.gone_quiet(db, silent_for_days=14) == []
    assert db.scalars(select(m.ActivityLog)).first().summary == "Called Kaimei about pricing"


def test_deal_numbers_are_sequential_within_the_year(db):
    assert svc.next_deal_no(db, date(2026, 3, 1)) == "DL-2026-0001"
    db.add(m.Deal(deal_no="DL-2026-0001", title="A"))
    db.commit()
    assert svc.next_deal_no(db, date(2026, 11, 1)) == "DL-2026-0002"
