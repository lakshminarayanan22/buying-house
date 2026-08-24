"""End-to-end flow through the HTTP surface: register -> profile -> submit -> verify -> find.

This is the §12 week-one goal exercised as one story, plus the negative case that matters most
— a brand searching the directory must get capability data with the identity withheld.
"""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as m
from app.auth import hash_password
from app.db import get_db
from app.enums import OrgStatus, OrgType, Role, UserStatus, VerificationStatus
from app.main import app
from app.seed.master_data import seed_master_data
from app.seed.notification_templates import seed_notification_templates


@pytest.fixture()
def client():
    # TestClient runs sync handlers in a threadpool, so every session must share one
    # in-memory connection — StaticPool plus check_same_thread off.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    m.Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    session = TestSession()
    seed_master_data(session)
    seed_notification_templates(session)
    session.close()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        test_client.session_factory = TestSession
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def _make_login(client, role: Role, org=None, password="Password123!") -> str:
    """Create a user directly and log in through the real endpoint."""
    db: Session = client.session_factory()
    user = m.User(
        org_id=org.id if org else None,
        role=role,
        name=f"{role.value} user",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password),
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.commit()
    email = user.email
    db.close()

    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_org(client, org_type: OrgType, name: str, status=OrgStatus.VERIFIED):
    db: Session = client.session_factory()
    org = m.Organization(type=org_type, legal_name=name, status=status)
    db.add(org)
    db.commit()
    db.refresh(org)
    db.close()
    return org


# --------------------------------------------------------------------------- happy path
def test_supplier_lifecycle_end_to_end(client):
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)

    # Tier 1: eight fields, and the aliases do the work — "sinker knitting" is not a code.
    response = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Kovai Knits Pvt Ltd",
            "city": "Tiruppur",
            "country_code": "India",
            "primary_process_code": "circular knitting",
            "primary_category_code": "tee",
            "contact_name": "R. Murugan",
            "phone": "+919000000001",
            "language_pref": "ta",
        },
    )
    assert response.status_code == 201, response.text
    org_id = response.json()["id"]

    # Tier 1 alone must not be submittable — capacity and MOQ are what make a profile usable.
    blocked = client.post(f"/api/suppliers/{org_id}/submit", headers=_auth(merch))
    assert blocked.status_code == 400
    assert "capacity" in blocked.json()["detail"].lower()

    for payload in [
        {
            "process_code": "circular knitting", "monthly_capacity_value": 250000,
            "capacity_uom": "PCS", "min_order_qty": 1000, "moq_uom": "PCS",
            "standard_lead_time_days": 45, "sample_lead_time_days": 10,
        },
        {
            "process_code": "CMT", "monthly_capacity_value": 180000, "capacity_uom": "PCS",
            "min_order_qty": 500, "moq_uom": "PCS", "standard_lead_time_days": 40,
            "sample_lead_time_days": 12,
        },
    ]:
        r = client.put(
            f"/api/suppliers/{org_id}/processes", headers=_auth(merch), json=payload
        )
        assert r.status_code == 200, r.text

    r = client.put(
        f"/api/suppliers/{org_id}/capabilities",
        headers=_auth(merch),
        json={
            "category_code": "tee", "fibre_codes": ["cotton", "organic cotton"],
            "construction_codes": ["S/J", "sinker"], "gsm_min": 140, "gsm_max": 220,
            "price_band_min": 2.1, "price_band_max": 4.8, "currency_code": "USD",
        },
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/suppliers/{org_id}/machines",
        headers=_auth(merch),
        json={"machine_type_code": "sinker machine", "count": 24, "make": "Mayer & Cie"},
    )
    assert r.status_code == 201, r.text

    client.patch(
        f"/api/organizations/{org_id}",
        headers=_auth(merch),
        json={"gst_no": "33AABCK1234M1Z5"},
    )

    completeness = client.get(
        f"/api/suppliers/{org_id}/completeness", headers=_auth(merch)
    ).json()
    assert completeness["tier"] == "TIER_2_PROFILED", completeness["missing"]
    assert completeness["completeness_pct"] >= 80

    submitted = client.post(f"/api/suppliers/{org_id}/submit", headers=_auth(merch))
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "SUBMITTED"

    # A merchandiser must not be able to verify their own submission.
    denied = client.post(
        f"/api/organizations/{org_id}/verification",
        headers=_auth(merch), json={"decision": "VERIFIED"},
    )
    assert denied.status_code == 403

    head = _make_login(client, Role.INTERNAL_SOURCING_HEAD)
    approved = client.post(
        f"/api/organizations/{org_id}/verification",
        headers=_auth(head), json={"decision": "VERIFIED", "notes": "Visited 12 Aug. Good unit."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "VERIFIED"

    found = client.get(
        "/api/directory/suppliers",
        headers=_auth(merch),
        params={"process": "circular knitting", "category": "Knitwear", "gsm": 180,
                "max_moq": 1500, "moq_uom": "PCS"},
    ).json()
    assert found["total"] == 1
    assert found["items"][0]["legal_name"] == "Kovai Knits Pvt Ltd"


def test_needs_info_requires_naming_what_is_missing(client):
    head = _make_login(client, Role.INTERNAL_SOURCING_HEAD)
    org = _make_org(client, OrgType.SUPPLIER, "Half Filled Unit", status=OrgStatus.SUBMITTED)

    vague = client.post(
        f"/api/organizations/{org.id}/verification",
        headers=_auth(head), json={"decision": "NEEDS_INFO", "notes": "incomplete"},
    )
    assert vague.status_code == 400

    specific = client.post(
        f"/api/organizations/{org.id}/verification",
        headers=_auth(head),
        json={"decision": "NEEDS_INFO", "requested_items": ["GOTS scope certificate", "GST"]},
    )
    assert specific.status_code == 200


# ------------------------------------------------------------------- identity gatekeeping
def test_brand_sees_capabilities_but_not_identity(client):
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    brand = _make_org(client, OrgType.BRAND, "Northwind Apparel Ltd")
    brand_token = _make_login(client, Role.BRAND_ADMIN, org=brand)

    created = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Erode Processors Pvt Ltd", "city": "Erode", "country_code": "IN",
            "primary_process_code": "process house", "primary_category_code": "T-shirts",
            "contact_name": "S. Kumar", "phone": "+919000000002",
        },
    ).json()
    org_id = created["id"]

    db: Session = client.session_factory()
    org = db.get(m.Organization, uuid.UUID(org_id))
    org.status = OrgStatus.VERIFIED
    db.commit()
    db.close()

    results = client.get("/api/directory/suppliers", headers=_auth(brand_token)).json()
    assert results["total"] == 1
    row = results["items"][0]

    # The capability data a brand needs to shortlist is present...
    assert row["city"] == "Erode"
    assert "Dyeing - fabric" in row["processes"]
    # ...and the identity that makes us disintermediable is not.
    assert "legal_name" not in row
    assert "trade_name" not in row
    assert "website" not in row
    assert row["is_identity_visible"] is False
    assert row["masked_ref"].startswith("SUP-")

    # Contacts are identity too, whichever endpoint you come in through.
    contacts = client.get(f"/api/organizations/{org_id}/contacts", headers=_auth(brand_token))
    assert contacts.status_code == 403

    # After an explicit reveal, the same search returns the name.
    db = client.session_factory()
    db.add(
        m.BrandSupplierReveal(
            brand_org_id=brand.id, supplier_org_id=uuid.UUID(org_id),
            brand_sees_supplier=True, reason="Shortlisted for AW26 enquiry",
        )
    )
    db.commit()
    db.close()

    revealed = client.get("/api/directory/suppliers", headers=_auth(brand_token)).json()
    assert revealed["items"][0]["legal_name"] == "Erode Processors Pvt Ltd"
    assert revealed["items"][0]["is_identity_visible"] is True


def test_supplier_cannot_browse_the_supplier_directory(client):
    supplier = _make_org(client, OrgType.SUPPLIER, "Kovai Knits Pvt Ltd")
    token = _make_login(client, Role.SUPPLIER_ADMIN, org=supplier)
    results = client.get("/api/directory/suppliers", headers=_auth(token)).json()
    assert results["total"] == 0


def test_unverified_suppliers_are_hidden_from_brands(client):
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    brand = _make_org(client, OrgType.BRAND, "Northwind Apparel Ltd")
    brand_token = _make_login(client, Role.BRAND_ADMIN, org=brand)

    client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Draft Unit", "city": "Salem", "country_code": "IN",
            "primary_process_code": "Stitching", "primary_category_code": "T-shirts",
            "contact_name": "A. Raja", "phone": "+919000000003",
        },
    )

    assert client.get("/api/directory/suppliers", headers=_auth(brand_token)).json()["total"] == 0
    # Internal staff can still see their own draft, on request.
    internal = client.get(
        "/api/directory/suppliers", headers=_auth(merch), params={"include_unverified": True}
    ).json()
    assert internal["total"] == 1


# --------------------------------------------------------------------------- filters
def test_certification_filter_excludes_expired_certificates(client):
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    org_id = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Certified Mills", "city": "Coimbatore", "country_code": "IN",
            "primary_process_code": "Knitting - circular", "primary_category_code": "T-shirts",
            "contact_name": "M. Selvam", "phone": "+919000000004",
        },
    ).json()["id"]

    client.post(
        f"/api/suppliers/{org_id}/certifications",
        headers=_auth(merch),
        json={
            "certification_code": "gots", "certificate_no": "CU-123456",
            "issued_on": str(date.today() - timedelta(days=800)),
            "valid_till": str(date.today() - timedelta(days=30)),
        },
    )

    db: Session = client.session_factory()
    org = db.get(m.Organization, uuid.UUID(org_id))
    org.status = OrgStatus.VERIFIED
    cert = db.scalars(select_cert(org.id)).first()
    cert.verification_status = VerificationStatus.VERIFIED  # verified, but expired
    db.commit()
    db.close()

    hits = client.get(
        "/api/directory/suppliers", headers=_auth(merch), params={"certification": "GOTS"}
    ).json()
    assert hits["total"] == 0, "an expired certificate must not satisfy a GOTS filter"

    db = client.session_factory()
    cert = db.scalars(select_cert(uuid.UUID(org_id))).first()
    cert.valid_till = date.today() + timedelta(days=200)
    db.commit()
    db.close()

    hits = client.get(
        "/api/directory/suppliers", headers=_auth(merch), params={"certification": "GOTS"}
    ).json()
    assert hits["total"] == 1


def select_cert(org_id):
    from sqlalchemy import select

    return select(m.SupplierCertification).where(m.SupplierCertification.org_id == org_id)


def test_unverified_certificate_does_not_satisfy_a_filter(client):
    """A claimed certificate is not a certificate. The filter exists because it is checked."""
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    org_id = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Claims GOTS Ltd", "city": "Karur", "country_code": "IN",
            "primary_process_code": "Weaving", "primary_category_code": "Bed linen",
            "contact_name": "K. Bala", "phone": "+919000000005",
        },
    ).json()["id"]

    client.post(
        f"/api/suppliers/{org_id}/certifications",
        headers=_auth(merch),
        json={"certification_code": "GOTS", "valid_till": str(date.today() + timedelta(days=300))},
    )
    db: Session = client.session_factory()
    org = db.get(m.Organization, uuid.UUID(org_id))
    org.status = OrgStatus.VERIFIED
    db.commit()
    db.close()

    hits = client.get(
        "/api/directory/suppliers", headers=_auth(merch), params={"certification": "GOTS"}
    ).json()
    assert hits["total"] == 0


def test_category_filter_matches_child_categories(client):
    """Filtering on Knitwear must return the T-shirt suppliers underneath it."""
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    org_id = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Subtree Knits", "city": "Tiruppur", "country_code": "IN",
            "primary_process_code": "Knitting - circular", "primary_category_code": "Polo shirts",
            "contact_name": "V. Ravi", "phone": "+919000000006",
        },
    ).json()["id"]

    db: Session = client.session_factory()
    db.get(m.Organization, uuid.UUID(org_id)).status = OrgStatus.VERIFIED
    db.commit()
    db.close()

    assert client.get(
        "/api/directory/suppliers", headers=_auth(merch), params={"category": "Apparel"}
    ).json()["total"] == 1
    assert client.get(
        "/api/directory/suppliers", headers=_auth(merch), params={"category": "Bed linen"}
    ).json()["total"] == 0


def test_moq_filter_compares_like_units(client):
    """A 500 kg MOQ must not satisfy a 1000-piece order."""
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    org_id = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Kilo Mills", "city": "Erode", "country_code": "IN",
            "primary_process_code": "Fabric dyeing", "primary_category_code": "T-shirts",
            "contact_name": "P. Anand", "phone": "+919000000007",
        },
    ).json()["id"]

    client.put(
        f"/api/suppliers/{org_id}/processes",
        headers=_auth(merch),
        json={"process_code": "Fabric dyeing", "min_order_qty": 500, "moq_uom": "KG"},
    )
    db: Session = client.session_factory()
    db.get(m.Organization, uuid.UUID(org_id)).status = OrgStatus.VERIFIED
    db.commit()
    db.close()

    assert client.get(
        "/api/directory/suppliers", headers=_auth(merch),
        params={"max_moq": 1000, "moq_uom": "PCS"},
    ).json()["total"] == 0
    assert client.get(
        "/api/directory/suppliers", headers=_auth(merch),
        params={"max_moq": 1000, "moq_uom": "KG"},
    ).json()["total"] == 1


# --------------------------------------------------------------------------- taxonomy
def test_unrecognised_fibre_is_queued_not_rejected(client):
    """A supplier must not be blocked mid-form because we have not added their term yet."""
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    org_id = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Novel Fibres Ltd", "city": "Madurai", "country_code": "IN",
            "primary_process_code": "Spinning", "primary_category_code": "T-shirts",
            "contact_name": "N. Iyer", "phone": "+919000000008",
        },
    ).json()["id"]

    saved = client.put(
        f"/api/suppliers/{org_id}/capabilities",
        headers=_auth(merch),
        json={"category_code": "T-shirts", "fibre_codes": ["cotton", "banana silk"]},
    )
    assert saved.status_code == 200

    admin = _make_login(client, Role.INTERNAL_SUPER_ADMIN)
    queue = client.get(
        "/api/master-data/unmapped", headers=_auth(admin), params={"domain": "FIBRE"}
    ).json()
    assert [t["raw_text"] for t in queue["items"]] == ["banana silk"]

    # Resolving it teaches the alias table, so the same word resolves silently next time.
    db: Session = client.session_factory()
    from sqlalchemy import select

    cotton = db.scalars(
        select(m.ReferenceItem).where(m.ReferenceItem.code == "COTTON")
    ).first()
    cotton_id = str(cotton.id)
    term_id = queue["items"][0]["id"]
    db.close()

    resolved = client.post(
        f"/api/master-data/unmapped/{term_id}/resolve",
        headers=_auth(admin), json={"item_id": cotton_id},
    )
    assert resolved.status_code == 200
    assert "banana silk" in resolved.json()["aliases"]


def test_merchandiser_cannot_edit_master_data(client):
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    response = client.post(
        "/api/master-data/items",
        headers=_auth(merch),
        json={"domain": "FIBRE", "code": "SEACELL", "name": "SeaCell"},
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- provenance
def test_provenance_records_who_entered_the_data(client):
    """A merchandiser's entry and a factory's self-report are not the same evidence."""
    merch = _make_login(client, Role.INTERNAL_MERCHANDISER)
    org_id = client.post(
        "/api/suppliers/register",
        headers=_auth(merch),
        json={
            "factory_name": "Provenance Mills", "city": "Salem", "country_code": "IN",
            "primary_process_code": "Knitting - circular", "primary_category_code": "T-shirts",
            "contact_name": "T. Ganesh", "phone": "+919000000009",
        },
    ).json()["id"]

    processes = client.get(f"/api/suppliers/{org_id}/processes", headers=_auth(merch)).json()
    assert processes[0]["source"] == "INTERNAL_VERIFIED"

    supplier_org = _make_org(client, OrgType.SUPPLIER, "Self Reporting Mills")
    supplier_token = _make_login(client, Role.SUPPLIER_ADMIN, org=supplier_org)
    client.put(
        f"/api/suppliers/{supplier_org.id}/processes",
        headers=_auth(supplier_token),
        json={"process_code": "Stitching", "monthly_capacity_value": 90000,
              "capacity_uom": "PCS"},
    )
    own = client.get(
        f"/api/suppliers/{supplier_org.id}/processes", headers=_auth(supplier_token)
    ).json()
    assert own[0]["source"] == "SELF_REPORTED"


def test_logout_invalidates_the_session(client):
    token = _make_login(client, Role.INTERNAL_MERCHANDISER)
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=_auth(token)).status_code == 200
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
