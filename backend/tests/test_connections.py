"""The commercial layer.

The cases are taken from how the business was actually described: sometimes a brand has fabric
already and needs only garmenting; sometimes they have their own stitching unit and need
knitting and dyeing. Both have to work without either being a special case.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import app.models as m
from app.enums import (
    ChainStageStatus,
    CommissionBasis,
    CommissionStatus,
    ConnectionStatus,
    OrgType,
    ReferenceDomain,
    Role,
)
from app.rbac import Action, can
from app.services import connections as svc
from app.services.taxonomy import resolve
from tests.conftest import make_org, make_user, principal_for


@pytest.fixture()
def taxonomy(db):
    """The real taxonomy, not the minimal one in conftest — these tests exercise actual process
    names ("Knitting - circular", "Stitching", "ginner") and the point is that they resolve."""
    from app.seed.master_data import seed_master_data

    seed_master_data(db)
    return True


@pytest.fixture()
def brand(db):
    return make_org(db, OrgType.BRAND, "Northwind Apparel Ltd")


def _process(db, name):
    item = resolve(db, ReferenceDomain.PROCESS_TYPE, name)
    assert item is not None, f"{name} missing from the taxonomy"
    return item


def _connection(db, brand, title="AW26 tee programme"):
    conn = m.Connection(
        connection_no=svc.next_connection_no(db), brand_org_id=brand.id, title=title,
    )
    db.add(conn)
    db.commit()
    return conn


# ------------------------------------------------------- the two shapes of a deal
def test_garmenting_only_is_a_chain_of_one(db, brand, taxonomy):
    """The brand already has fabric; we connect them to a stitching unit and nothing else."""
    unit = make_org(db, OrgType.SUPPLIER, "Tiruppur Stitching Co")
    conn = _connection(db, brand, "Fabric in hand — need CMT only")

    db.add(m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=unit.id,
        process_type_id=_process(db, "Stitching").id, sequence=1,
        qty=12000, qty_uom="PCS", order_value=48000,
        commission_basis=CommissionBasis.SUPPLIER_COMMISSION, commission_pct=4,
    ))
    db.commit()
    db.refresh(conn)

    assert len(conn.stages) == 1
    svc.refresh_commission(conn.stages[0])
    assert conn.stages[0].commission_amount == 1920.0   # 4% of 48,000


def test_brand_with_its_own_stitching_needs_two_stages(db, brand, taxonomy):
    """They garment in-house, so we cover knitting and dyeing — two suppliers, one deal."""
    mill = make_org(db, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")
    dyer = make_org(db, OrgType.SUPPLIER, "Erode Processors Pvt Ltd")
    conn = _connection(db, brand, "Greige and dyeing for in-house garmenting")

    db.add_all([
        m.ConnectionStage(
            connection_id=conn.id, supplier_org_id=mill.id,
            process_type_id=_process(db, "Knitting - circular").id, sequence=1,
            qty=9000, qty_uom="KG", order_value=27000,
            commission_basis=CommissionBasis.SUPPLIER_COMMISSION, commission_pct=3,
        ),
        m.ConnectionStage(
            connection_id=conn.id, supplier_org_id=dyer.id,
            process_type_id=_process(db, "Fabric dyeing").id, sequence=2,
            qty=9000, qty_uom="KG", order_value=13500,
            commission_basis=CommissionBasis.SUPPLIER_COMMISSION, commission_pct=5,
        ),
    ])
    db.commit()
    db.refresh(conn)

    assert [s.sequence for s in conn.stages] == [1, 2]
    for stage in conn.stages:
        svc.refresh_commission(stage)
    db.commit()
    assert conn.commission_total == 810.0 + 675.0
    assert conn.order_value_total == 40500.0


def test_one_supplier_can_cover_two_stages(db, brand, taxonomy):
    """A mill that knits and dyes is two rows against the same supplier — the normal case for a
    vertically integrated unit, not an error."""
    mill = make_org(db, OrgType.SUPPLIER, "Integrated Mills Ltd")
    conn = _connection(db, brand)

    db.add_all([
        m.ConnectionStage(connection_id=conn.id, supplier_org_id=mill.id,
                          process_type_id=_process(db, "Knitting - circular").id, sequence=1,
                          commission_basis=CommissionBasis.NONE),
        m.ConnectionStage(connection_id=conn.id, supplier_org_id=mill.id,
                          process_type_id=_process(db, "Fabric dyeing").id, sequence=2,
                          commission_basis=CommissionBasis.NONE),
    ])
    db.commit()
    assert len(db.scalars(select(m.ConnectionStage)).all()) == 2


def test_the_same_supplier_cannot_cover_the_same_stage_twice(db, brand, taxonomy):
    mill = make_org(db, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")
    conn = _connection(db, brand)
    knit = _process(db, "Knitting - circular").id

    db.add(m.ConnectionStage(connection_id=conn.id, supplier_org_id=mill.id,
                             process_type_id=knit, commission_basis=CommissionBasis.NONE))
    db.commit()
    db.add(m.ConnectionStage(connection_id=conn.id, supplier_org_id=mill.id,
                             process_type_id=knit, commission_basis=CommissionBasis.NONE))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_ginning_and_fabric_trading_exist(db, taxonomy):
    """Both were named as supplier types and neither was in the taxonomy before."""
    for name in ["ginner", "ginning", "fabric trader", "yarn agent"]:
        assert resolve(db, ReferenceDomain.PROCESS_TYPE, name) is not None, name


# --------------------------------------------------------------------- commission
def test_markup_commission_is_the_gap_times_the_quantity(db, brand, taxonomy):
    unit = make_org(db, OrgType.SUPPLIER, "Tiruppur Stitching Co")
    conn = _connection(db, brand)

    stage = m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=unit.id,
        process_type_id=_process(db, "Stitching").id,
        qty=10000, qty_uom="PCS", supplier_price=3.20, brand_price=3.65,
        commission_basis=CommissionBasis.BRAND_MARKUP,
    )
    db.add(stage)
    db.commit()

    svc.refresh_commission(stage)
    assert stage.commission_amount == 4500.0   # 0.45 x 10,000


def test_a_negotiated_commission_survives_recalculation(db, brand, taxonomy):
    """A merchandiser who typed in an agreed figure should not have it silently overwritten."""
    unit = make_org(db, OrgType.SUPPLIER, "Tiruppur Stitching Co")
    conn = _connection(db, brand)
    stage = m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=unit.id,
        process_type_id=_process(db, "Stitching").id, order_value=50000,
        commission_basis=CommissionBasis.SUPPLIER_COMMISSION, commission_pct=4,
        commission_amount=1750,
    )
    db.add(stage)
    db.commit()

    svc.refresh_commission(stage)
    assert stage.commission_amount == 1750       # left alone
    svc.refresh_commission(stage, overwrite=True)
    assert stage.commission_amount == 2000.0     # only when asked


def test_a_markup_cannot_be_negative(db, brand, taxonomy):
    """Quoting the brand below the supplier price is a typo, not a deal."""
    unit = make_org(db, OrgType.SUPPLIER, "Tiruppur Stitching Co")
    conn = _connection(db, brand)
    db.add(m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=unit.id,
        process_type_id=_process(db, "Stitching").id,
        qty=100, supplier_price=4.00, brand_price=3.50,
        commission_basis=CommissionBasis.BRAND_MARKUP,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_a_commission_percentage_is_required_when_that_is_the_basis(db, brand, taxonomy):
    unit = make_org(db, OrgType.SUPPLIER, "Tiruppur Stitching Co")
    conn = _connection(db, brand)
    db.add(m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=unit.id,
        process_type_id=_process(db, "Stitching").id,
        commission_basis=CommissionBasis.SUPPLIER_COMMISSION,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cannot_invoice_a_commission_with_no_amount(db, brand, taxonomy):
    unit = make_org(db, OrgType.SUPPLIER, "Tiruppur Stitching Co")
    conn = _connection(db, brand)
    db.add(m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=unit.id,
        process_type_id=_process(db, "Stitching").id,
        commission_basis=CommissionBasis.NONE,
        commission_status=CommissionStatus.INVOICED,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --------------------------------------------------------------- reveal and status
def test_introducing_a_stage_reveals_the_supplier_to_the_brand(db, brand, taxonomy):
    """Telling a brand the factory's name on a call and leaving the database saying they have
    never met is how the identity gate quietly stops meaning anything."""
    mill = make_org(db, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")
    conn = _connection(db, brand)
    stage = m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=mill.id,
        process_type_id=_process(db, "Knitting - circular").id,
        commission_basis=CommissionBasis.NONE, status=ChainStageStatus.PROPOSED,
    )
    db.add(stage)
    db.commit()

    svc.ensure_reveal(db, conn, stage)
    db.commit()
    assert db.scalars(select(m.BrandSupplierReveal)).first() is None  # still only proposed

    stage.status = ChainStageStatus.INTRODUCED
    svc.ensure_reveal(db, conn, stage)
    db.commit()

    reveal = db.scalars(select(m.BrandSupplierReveal)).first()
    assert reveal is not None
    assert reveal.brand_sees_supplier is True
    # One direction only — the supplier does not automatically learn who the brand is.
    assert reveal.supplier_sees_brand is False


def test_connection_status_follows_its_slowest_live_stage(db, brand, taxonomy):
    mill = make_org(db, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")
    dyer = make_org(db, OrgType.SUPPLIER, "Erode Processors Pvt Ltd")
    conn = _connection(db, brand)
    db.add_all([
        m.ConnectionStage(connection_id=conn.id, supplier_org_id=mill.id,
                          process_type_id=_process(db, "Knitting - circular").id,
                          commission_basis=CommissionBasis.NONE,
                          status=ChainStageStatus.IN_PRODUCTION),
        m.ConnectionStage(connection_id=conn.id, supplier_org_id=dyer.id,
                          process_type_id=_process(db, "Fabric dyeing").id,
                          commission_basis=CommissionBasis.NONE,
                          status=ChainStageStatus.SAMPLING),
    ])
    db.commit()
    db.refresh(conn)
    assert svc.roll_up_status(conn) == ConnectionStatus.SAMPLING

    # A dropped supplier must not hold the whole deal back.
    conn.stages[1].status = ChainStageStatus.DROPPED
    db.commit()
    db.refresh(conn)
    assert svc.roll_up_status(conn) == ConnectionStatus.IN_PRODUCTION


def test_connection_numbers_are_sequential_within_the_year(db, brand):
    first = svc.next_connection_no(db, date(2026, 3, 1))
    db.add(m.Connection(connection_no=first, brand_org_id=brand.id, title="A"))
    db.commit()
    assert first == "CN-2026-0001"
    assert svc.next_connection_no(db, date(2026, 9, 1)) == "CN-2026-0002"


# ---------------------------------------------------------------- the four views
@pytest.fixture()
def tracker_data(db, brand, taxonomy):
    mill = make_org(db, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")
    dyer = make_org(db, OrgType.SUPPLIER, "Erode Processors Pvt Ltd")
    conn = _connection(db, brand)
    db.add_all([
        m.ConnectionStage(
            connection_id=conn.id, supplier_org_id=mill.id,
            process_type_id=_process(db, "Knitting - circular").id,
            order_value=30000, commission_basis=CommissionBasis.SUPPLIER_COMMISSION,
            commission_pct=3, commission_amount=900,
            commission_status=CommissionStatus.INVOICED, invoiced_on=date.today(),
            ship_date=date.today() + timedelta(days=20), status=ChainStageStatus.IN_PRODUCTION,
        ),
        m.ConnectionStage(
            connection_id=conn.id, supplier_org_id=dyer.id,
            process_type_id=_process(db, "Fabric dyeing").id,
            order_value=12000, commission_basis=CommissionBasis.SUPPLIER_COMMISSION,
            commission_pct=5, commission_amount=600,
            commission_status=CommissionStatus.RECEIVED,
            invoiced_on=date.today() - timedelta(days=30),
            received_on=date.today() - timedelta(days=5),
            ship_date=date.today() - timedelta(days=3), status=ChainStageStatus.SHIPPED,
        ),
    ])
    db.commit()
    return conn


def test_commission_ledger_separates_owed_from_received(db, tracker_data):
    ledger = {row["bucket"]: row["amount"] for row in svc.commission_ledger(db)}
    assert ledger["INVOICED"] == 900.0
    assert ledger["RECEIVED"] == 600.0
    assert ledger["OUTSTANDING"] == 900.0


def test_supplier_earnings_ranks_by_what_they_earn_us(db, tracker_data):
    rows = svc.supplier_earnings(db)
    assert [r["supplier"] for r in rows] == ["Kovai Knits Pvt Ltd", "Erode Processors Pvt Ltd"]
    assert rows[0]["commission"] == 900.0
    assert rows[0]["order_value"] == 30000.0


def test_upcoming_shipments_flags_the_overdue_one(db, tracker_data):
    rows = svc.upcoming_shipments(db)
    assert len(rows) == 2
    overdue = [r for r in rows if r["overdue"]]
    assert len(overdue) == 1
    assert overdue[0]["stage"] == "Dyeing - fabric"
    assert overdue[0]["days_out"] == -3


def test_pipeline_reports_value_by_status(db, tracker_data):
    rows = {r["status"]: r for r in svc.pipeline(db)}
    assert rows["SCOPING"]["connections"] == 1
    assert rows["SCOPING"]["order_value"] == 42000.0


# --------------------------------------------------------------------- access
def test_the_commercial_record_is_internal_only(db, brand, taxonomy):
    """supplier_price and brand_price sit on the same row. A brand reading one would learn
    exactly what we make on the deal."""
    mill = make_org(db, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")
    conn = _connection(db, brand)
    stage = m.ConnectionStage(
        connection_id=conn.id, supplier_org_id=mill.id,
        process_type_id=_process(db, "Knitting - circular").id,
        commission_basis=CommissionBasis.NONE,
    )
    db.add(stage)
    db.commit()

    brand_actor = principal_for(make_user(db, brand, Role.BRAND_ADMIN), brand)
    supplier_actor = principal_for(make_user(db, mill, Role.SUPPLIER_ADMIN), mill)
    for actor in (brand_actor, supplier_actor):
        assert not can(actor, Action.VIEW, conn)
        assert not can(actor, Action.VIEW, stage)

    internal = principal_for(make_user(db, None, Role.INTERNAL_MERCHANDISER), None)
    assert can(internal, Action.VIEW, conn)
    assert can(internal, Action.VIEW, stage)
