"""The natural-language record editor.

The property that matters most: a preview must leave the database exactly as it found it.
Everything else — the guard, the diff, the conflict check — is tested against that baseline.
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.models as m
from app.auth import hash_password
from app.db import get_db
from app.enums import OrgType, Role, UserStatus
from app.main import app
from app.nlsql.guard import SqlRejected, validate
from app.nlsql.preview import ChangeConflict, apply_change, preview_sql
from app.rbac import Principal
from app.seed.master_data import seed_master_data


# This feature is Postgres-specific — the guard emits Postgres SQL, and the preview relies on
# RETURNING and SAVEPOINTs. Running it against SQLite would test a different dialect: SQLite
# stores UUIDs as dashless hex, so a literal 'a1b2-...' silently matches nothing and every
# preview would look like a no-op. These tests need the real database or they are worthless.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://bh:bh@localhost:5432/buyinghouse_test"
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(TEST_DATABASE_URL)
        with engine.connect():
            pass
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason=f"needs Postgres at {TEST_DATABASE_URL} (createdb buyinghouse_test)",
)


@pytest.fixture()
def client():
    engine = create_engine(TEST_DATABASE_URL)
    m.Base.metadata.drop_all(engine)
    m.Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = TestSession()
    seed_master_data(session)
    session.close()

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        c.session_factory = TestSession
        yield c
    app.dependency_overrides.clear()
    m.Base.metadata.drop_all(engine)
    engine.dispose()


def _login(client, role: Role) -> str:
    db: Session = client.session_factory()
    user = m.User(
        role=role, name=f"{role} user", email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("Password123!"), status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.commit()
    email = user.email
    db.close()
    r = client.post("/api/auth/login", json={"email": email, "password": "Password123!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def supplier_with_moq(client):
    """A supplier with one process carrying a wrong MOQ, ready to be corrected."""
    db: Session = client.session_factory()
    org = m.Organization(type=OrgType.SUPPLIER, legal_name="Kovai Knits Pvt Ltd", city="Tiruppur")
    db.add(org)
    db.flush()
    knitting = db.scalars(
        select(m.ReferenceItem).where(m.ReferenceItem.code == "KNITTING_CIRCULAR")
    ).first()
    process = m.SupplierProcess(
        org_id=org.id, process_type_id=knitting.id, min_order_qty=5000, moq_uom="PCS",
        monthly_capacity_value=250000, capacity_uom="PCS",
    )
    db.add(process)
    db.commit()
    ids = (org.id, process.id)
    db.close()
    return ids


# --------------------------------------------------------------- the core guarantee
def test_preview_does_not_change_the_database(client, supplier_with_moq):
    """The whole design rests on this: previewing must commit nothing."""
    _org_id, process_id = supplier_with_moq
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)

    response = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={
            "prompt": "Kovai Knits' minimum order is 1000 pieces, not 5000",
            "sql": f"UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '{process_id}'",
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()

    # The diff describes a real change...
    assert preview["affected_count"] == 1
    assert preview["status"] == "PREVIEWED"
    changes = preview["diff"][0]["changes"]
    assert changes["min_order_qty"]["before"] == 5000
    assert changes["min_order_qty"]["after"] == 1000

    # ...and the database still holds the old value.
    db: Session = client.session_factory()
    assert db.get(m.SupplierProcess, process_id).min_order_qty == 5000
    db.close()


def test_confirm_applies_the_change_and_logs_every_row(client, supplier_with_moq):
    _org_id, process_id = supplier_with_moq
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)

    change_id = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={
            "prompt": "Set Kovai Knits MOQ to 1000 pieces",
            "sql": f"UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '{process_id}'",
        },
    ).json()["id"]

    confirmed = client.post(f"/api/nlsql/{change_id}/confirm", headers=_auth(token))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "APPLIED"

    db: Session = client.session_factory()
    assert db.get(m.SupplierProcess, process_id).min_order_qty == 1000

    logs = db.scalars(
        select(m.ActivityLog).where(m.ActivityLog.entity_type == "supplier_process")
    ).all()
    assert len(logs) == 1
    assert logs[0].before["min_order_qty"] == 5000
    assert logs[0].after["min_order_qty"] == 1000
    assert "Natural-language edit" in logs[0].summary
    db.close()


def test_confirm_is_refused_when_the_rows_changed_underneath(client, supplier_with_moq):
    """Between preview and confirm somebody else edited the same row. Applying anyway would
    overwrite their work with a diff the reviewer never saw."""
    _org_id, process_id = supplier_with_moq
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)

    change_id = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={
            "prompt": "Set MOQ to 1000",
            "sql": f"UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '{process_id}'",
        },
    ).json()["id"]

    db: Session = client.session_factory()
    db.get(m.SupplierProcess, process_id).min_order_qty = 2500
    db.commit()
    db.close()

    conflicted = client.post(f"/api/nlsql/{change_id}/confirm", headers=_auth(token))
    assert conflicted.status_code == 409
    assert "changed since you previewed" in conflicted.json()["detail"]

    db = client.session_factory()
    assert db.get(m.SupplierProcess, process_id).min_order_qty == 2500  # untouched
    db.close()


def test_a_change_cannot_be_confirmed_twice(client, supplier_with_moq):
    _org_id, process_id = supplier_with_moq
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)
    change_id = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={"prompt": "Set MOQ to 1000",
              "sql": f"UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '{process_id}'"},
    ).json()["id"]

    assert client.post(f"/api/nlsql/{change_id}/confirm", headers=_auth(token)).status_code == 200
    assert client.post(f"/api/nlsql/{change_id}/confirm", headers=_auth(token)).status_code == 409


def test_discarded_change_never_applies(client, supplier_with_moq):
    _org_id, process_id = supplier_with_moq
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)
    change_id = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={"prompt": "Set MOQ to 1000",
              "sql": f"UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '{process_id}'"},
    ).json()["id"]

    assert client.post(f"/api/nlsql/{change_id}/discard", headers=_auth(token)).status_code == 200
    assert client.post(f"/api/nlsql/{change_id}/confirm", headers=_auth(token)).status_code == 409

    db: Session = client.session_factory()
    assert db.get(m.SupplierProcess, process_id).min_order_qty == 5000
    db.close()


# --------------------------------------------------------------------------- access
def test_only_super_admins_may_use_the_editor(client, supplier_with_moq):
    _org_id, process_id = supplier_with_moq
    for role in (Role.INTERNAL_MERCHANDISER, Role.INTERNAL_SOURCING_HEAD, Role.INTERNAL_QA,
                 Role.INTERNAL_MANAGEMENT):
        token = _login(client, role)
        response = client.post(
            "/api/nlsql/propose",
            headers=_auth(token),
            json={"prompt": "x", "sql": f"UPDATE supplier_process SET min_order_qty=1 "
                                        f"WHERE id='{process_id}'"},
        )
        assert response.status_code == 403, role


# ------------------------------------------------------------------------- the guard
@pytest.mark.parametrize(
    "sql,fragment",
    [
        ("UPDATE supplier_process SET min_order_qty = 1", "no WHERE clause"),
        ("DROP TABLE organization", "Only INSERT, UPDATE and DELETE"),
        ("ALTER TABLE organization ADD COLUMN x int", "Only INSERT, UPDATE and DELETE"),
        ("UPDATE app_user SET role='INTERNAL_SUPER_ADMIN' WHERE id='1'", "never writable"),
        ("DELETE FROM activity_log WHERE id='1'", "audit trail"),
        ("UPDATE brand_supplier_reveal SET brand_sees_supplier=true WHERE id='1'", "never writable"),
        ("UPDATE supplier_performance SET composite_score=99 WHERE org_id='1'", "never writable"),
        ("UPDATE contact SET name='x' WHERE id='1'; DROP TABLE note", "one statement"),
        ("UPDATE contact SET name=pg_read_file('/etc/passwd') WHERE id='1'", "not permitted"),
    ],
)
def test_guard_rejects_dangerous_statements(client, sql, fragment):
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)
    response = client.post(
        "/api/nlsql/propose", headers=_auth(token), json={"prompt": "test", "sql": sql}
    )
    assert response.status_code == 400, response.text
    assert fragment in response.json()["detail"], response.json()["detail"]


def test_row_limit_refuses_an_overbroad_change(client):
    """A statement that touches far more rows than expected is usually a bad WHERE clause."""
    db: Session = client.session_factory()
    for i in range(6):
        db.add(m.Organization(type=OrgType.SUPPLIER, legal_name=f"Unit {i}", city="Tiruppur"))
    db.commit()
    db.close()

    token = _login(client, Role.INTERNAL_SUPER_ADMIN)
    response = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={
            "prompt": "Move every Tiruppur supplier to Coimbatore",
            "sql": "UPDATE organization SET city = 'Coimbatore' WHERE city = 'Tiruppur'",
            "max_rows": 3,
        },
    )
    assert response.status_code == 413
    assert "6 rows" in response.json()["detail"]

    db = client.session_factory()
    still_tiruppur = db.scalars(
        select(m.Organization).where(m.Organization.city == "Tiruppur")
    ).all()
    assert len(still_tiruppur) == 6  # the refused preview changed nothing
    db.close()


def test_a_failing_statement_leaves_no_trace(client, supplier_with_moq):
    """A statement that errors mid-preview must still roll back cleanly, not poison the session."""
    _org_id, process_id = supplier_with_moq
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)

    bad = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={"prompt": "break it",
              "sql": "UPDATE supplier_process SET no_such_column = 1 WHERE id = '1'"},
    )
    assert bad.status_code == 400

    # The session recovers: a valid change still previews afterwards.
    good = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={"prompt": "Set MOQ to 1000",
              "sql": f"UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '{process_id}'"},
    )
    assert good.status_code == 200, good.text


def test_delete_preview_shows_the_rows_that_would_go(client, supplier_with_moq):
    org_id, _process_id = supplier_with_moq
    db: Session = client.session_factory()
    db.add(m.Contact(org_id=org_id, name="Old Contact", phone="+919000000000"))
    db.commit()
    db.close()

    token = _login(client, Role.INTERNAL_SUPER_ADMIN)
    preview = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={"prompt": "Remove the old contact for Kovai Knits",
              "sql": f"DELETE FROM contact WHERE org_id = '{org_id}'"},
    ).json()

    assert preview["affected_count"] == 1
    assert preview["diff"][0]["operation"] == "DELETE"
    assert preview["diff"][0]["before"]["name"] == "Old Contact"

    db = client.session_factory()
    assert db.scalars(select(m.Contact).where(m.Contact.org_id == org_id)).all()  # still there
    db.close()


def test_insert_preview_shows_the_new_row(client):
    db: Session = client.session_factory()
    item = db.scalars(
        select(m.ReferenceItem).where(m.ReferenceItem.code == "SINGLE_JERSEY")
    ).first()
    item_id = item.id
    db.close()

    token = _login(client, Role.INTERNAL_SUPER_ADMIN)
    preview = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={
            "prompt": "Teach the taxonomy that 'plated jersey' means Single Jersey",
            "sql": (
                f"INSERT INTO reference_alias (id, item_id, alias, normalised, language) "
                f"VALUES ('{uuid.uuid4()}', '{item_id}', 'Plated Jersey', 'plated jersey', 'en')"
            ),
        },
    ).json()

    assert preview["affected_count"] == 1
    assert preview["diff"][0]["operation"] == "INSERT"
    assert preview["diff"][0]["after"]["alias"] == "Plated Jersey"

    db = client.session_factory()
    assert db.scalars(
        select(m.ReferenceAlias).where(m.ReferenceAlias.normalised == "plated jersey")
    ).first() is None
    db.close()


def test_updated_at_is_not_shown_as_a_change(client, supplier_with_moq):
    """It moves on every write; listing it would bury the change the reviewer cares about."""
    _org_id, process_id = supplier_with_moq
    token = _login(client, Role.INTERNAL_SUPER_ADMIN)
    preview = client.post(
        "/api/nlsql/propose",
        headers=_auth(token),
        json={"prompt": "Set MOQ to 1000",
              "sql": f"UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '{process_id}'"},
    ).json()
    assert list(preview["diff"][0]["changes"]) == ["min_order_qty"]
