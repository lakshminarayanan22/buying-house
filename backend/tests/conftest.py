"""Test fixtures. SQLite in-memory with foreign keys ON, so composite taxonomy FKs are live."""
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.models as m
from app.enums import OrgStatus, OrgType, ReferenceDomain, Role, UserStatus
from app.rbac import Principal


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    m.Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def taxonomy(db) -> dict:
    """A minimal but real taxonomy: one value per domain the tests touch."""
    items = {
        "knitting": m.ReferenceItem(
            domain=ReferenceDomain.PROCESS_TYPE, code="KNITTING", name="Knitting"
        ),
        "dyeing": m.ReferenceItem(
            domain=ReferenceDomain.PROCESS_TYPE, code="FABRIC_DYEING", name="Fabric dyeing"
        ),
        "tshirt": m.ReferenceItem(
            domain=ReferenceDomain.PRODUCT_CATEGORY, code="TSHIRT", name="T-shirts",
            path="APPAREL/KNITWEAR/TSHIRT", depth=2,
        ),
        "cotton": m.ReferenceItem(domain=ReferenceDomain.FIBRE, code="COTTON", name="Cotton"),
        "single_jersey": m.ReferenceItem(
            domain=ReferenceDomain.FABRIC_CONSTRUCTION, code="SINGLE_JERSEY", name="Single Jersey"
        ),
        "gots": m.ReferenceItem(
            domain=ReferenceDomain.CERTIFICATION, code="GOTS", name="GOTS"
        ),
        "india": m.ReferenceItem(domain=ReferenceDomain.COUNTRY, code="IN", name="India"),
        "usd": m.ReferenceItem(domain=ReferenceDomain.CURRENCY, code="USD", name="US Dollar"),
    }
    db.add_all(items.values())
    db.commit()
    return items


def make_org(db, org_type: OrgType, name: str, status: OrgStatus = OrgStatus.VERIFIED):
    org = m.Organization(type=org_type, legal_name=name, status=status)
    db.add(org)
    db.commit()
    return org


def make_user(db, org, role: Role, name: str = "Test User"):
    user = m.User(
        org_id=org.id if org else None,
        role=role,
        name=name,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.commit()
    return user


def principal_for(user, org=None, revealed: set | None = None) -> Principal:
    return Principal(
        user_id=user.id,
        role=Role(user.role),
        org_id=user.org_id,
        org_type=OrgType(org.type) if org else None,
        status=UserStatus(user.status),
        revealed_org_ids=frozenset(revealed or set()),
    )


@pytest.fixture()
def brand(db):
    return make_org(db, OrgType.BRAND, "Northwind Apparel Ltd")


@pytest.fixture()
def supplier(db):
    return make_org(db, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")


@pytest.fixture()
def other_supplier(db):
    return make_org(db, OrgType.SUPPLIER, "Erode Processors Pvt Ltd")


@pytest.fixture()
def brand_principal(db, brand):
    return principal_for(make_user(db, brand, Role.BRAND_ADMIN), brand)


@pytest.fixture()
def supplier_principal(db, supplier):
    return principal_for(make_user(db, supplier, Role.SUPPLIER_ADMIN), supplier)


@pytest.fixture()
def merchandiser_principal(db):
    return principal_for(make_user(db, None, Role.INTERNAL_MERCHANDISER), None)
