"""Google sign-in, the approval queue, and the two guards over it.

Driven through the HTTP API rather than the service functions wherever possible, because the
thing that matters is what a person at the login screen can and can't reach.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models as m
from app.auth import create_session_token, hash_password
from app.config import settings
from app.db import get_db
from app.enums import ActivityAction, UserRole, UserStatus
from app.main import app
from app.services import access

DOMAIN = "ecolinksolutions.in"


@pytest.fixture()
def env(monkeypatch):
    """A fresh database, the stub Google backend, and a captured outbox."""
    # One shared connection: an in-memory SQLite database exists per connection, and the test
    # client serves requests on a different thread from the one that created the tables.
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    tables = [t for name, t in m.Base.metadata.tables.items() if name != "document_chunk"]
    m.Base.metadata.create_all(engine, tables=tables)

    def _db():
        with Session(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(settings, "environment", "local")
    monkeypatch.setattr(settings, "google_auth_backend", "stub")
    monkeypatch.setattr(settings, "allowed_email_domain", DOMAIN)
    monkeypatch.setattr(settings, "bootstrap_admin_emails", f"boss@{DOMAIN}")

    outbox = []
    monkeypatch.setattr("app.services.mailer.send", lambda email: outbox.append(email) or True)

    class Env:
        client = TestClient(app)
        sent = outbox

        @staticmethod
        def db() -> Session:
            return Session(engine, expire_on_commit=False)

        @staticmethod
        def google(email: str, name: str = ""):
            return Env.client.post("/api/auth/google",
                                   json={"credential": f"stub:{email}|{name}"})

        @staticmethod
        def user(email: str) -> m.User:
            with Env.db() as s:
                return s.scalars(select(m.User).where(m.User.email == email)).one()

        @staticmethod
        def as_(email: str) -> dict:
            u = Env.user(email)
            return {"Authorization": f"Bearer {create_session_token(u.id, u.token_version)}"}

    yield Env
    app.dependency_overrides.clear()
    engine.dispose()


def _admin(env) -> dict:
    assert env.google(f"boss@{DOMAIN}", "The Boss").json()["status"] == "ACTIVE"
    return env.as_(f"boss@{DOMAIN}")


# ------------------------------------------------------------------------ the front door
def test_other_domains_are_refused_and_leave_no_trace(env):
    for email in ("someone@gmail.com", f"someone@{DOMAIN}.evil.com", "someone@notecolinksolutions.in"):
        r = env.google(email)
        assert r.status_code == 403, email
    with env.db() as s:
        assert s.scalars(select(m.User)).all() == []


def test_first_sign_in_waits_for_approval_and_tells_admins_once(env):
    _admin(env)
    env.sent.clear()

    r = env.google(f"priya@{DOMAIN}", "Priya Raman")
    body = r.json()
    assert r.status_code == 200
    assert body["status"] == "PENDING"
    assert body["access_token"] is None
    assert body["newly_requested"] is True

    assert len(env.sent) == 1
    assert env.sent[0].to == (f"boss@{DOMAIN}",)
    assert "Priya Raman" in env.sent[0].subject

    # Signing in again while waiting is not a second request, and not a second email.
    again = env.google(f"priya@{DOMAIN}", "Priya Raman").json()
    assert again["status"] == "PENDING" and again["newly_requested"] is False
    assert len(env.sent) == 1


def test_a_pending_account_cannot_use_a_token_even_if_it_had_one(env):
    env.google(f"priya@{DOMAIN}")
    r = env.client.get("/api/auth/me", headers=env.as_(f"priya@{DOMAIN}"))
    assert r.status_code == 401


def test_approval_is_one_time(env):
    admin = _admin(env)
    env.google(f"priya@{DOMAIN}", "Priya Raman")
    env.sent.clear()

    priya = env.user(f"priya@{DOMAIN}")
    r = env.client.post(f"/api/users/{priya.id}/approve", json={"role": "MEMBER"}, headers=admin)
    assert r.status_code == 200
    assert r.json()["status"] == "ACTIVE"
    assert r.json()["reviewed_by_name"] == "The Boss"
    assert env.sent and env.sent[0].to == (f"priya@{DOMAIN}",)

    # From now on, straight in, every time.
    for _ in range(2):
        body = env.google(f"priya@{DOMAIN}", "Priya Raman").json()
        assert body["status"] == "ACTIVE" and body["access_token"]
    me = env.client.get("/api/auth/me",
                        headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["email"] == f"priya@{DOMAIN}"
    assert me.json()["role"] == "MEMBER"


def test_bootstrap_admin_is_let_in_by_configuration(env):
    body = env.google(f"boss@{DOMAIN}", "The Boss").json()
    assert body["status"] == "ACTIVE" and body["access_token"]

    boss = env.user(f"boss@{DOMAIN}")
    assert boss.role == UserRole.ADMIN
    assert boss.reviewed_by_id is None     # approved by config, not by a person
    with env.db() as s:
        log = s.scalars(select(m.ActivityLog).where(
            m.ActivityLog.action == ActivityAction.ACCESS_APPROVED)).one()
        assert "BOOTSTRAP_ADMIN_EMAILS" in log.summary


def test_declined_then_reconsidered(env):
    admin = _admin(env)
    env.google(f"sam@{DOMAIN}")
    sam = env.user(f"sam@{DOMAIN}")

    assert env.client.post(f"/api/users/{sam.id}/reject", headers=admin).status_code == 200
    assert env.google(f"sam@{DOMAIN}").json()["status"] == "REJECTED"

    r = env.client.post(f"/api/users/{sam.id}/approve", json={"role": "MEMBER"}, headers=admin)
    assert r.json()["status"] == "ACTIVE"
    assert env.google(f"sam@{DOMAIN}").json()["status"] == "ACTIVE"


# ------------------------------------------------------------------ switching someone off
def test_disabling_closes_both_doors_and_every_open_session(env):
    admin = _admin(env)
    env.google(f"priya@{DOMAIN}")
    priya = env.user(f"priya@{DOMAIN}")
    env.client.post(f"/api/users/{priya.id}/approve", json={"role": "MEMBER"}, headers=admin)

    # Priya adds a password, so she has two ways in and an open session.
    token = env.google(f"priya@{DOMAIN}").json()["access_token"]
    r = env.client.post("/api/auth/password", json={"new_password": "correct horse battery"},
                        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    session = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert env.client.get("/api/auth/me", headers=session).status_code == 200

    assert env.client.post(f"/api/users/{priya.id}/disable", headers=admin).status_code == 200

    assert env.client.get("/api/auth/me", headers=session).status_code == 401
    assert env.google(f"priya@{DOMAIN}").json()["status"] == "DISABLED"
    pw = env.client.post("/api/auth/login",
                         json={"email": f"priya@{DOMAIN}", "password": "correct horse battery"})
    assert pw.status_code == 401

    env.client.post(f"/api/users/{priya.id}/restore", headers=admin)
    assert env.google(f"priya@{DOMAIN}").json()["status"] == "ACTIVE"
    # Restoring access must not resurrect sessions from before it was switched off — the
    # laptop she left signed in on the day she was disabled stays signed out.
    assert env.client.get("/api/auth/me", headers=session).status_code == 401


def test_an_admin_cannot_act_on_their_own_access(env):
    admin = _admin(env)
    boss = env.user(f"boss@{DOMAIN}")
    assert env.client.post(f"/api/users/{boss.id}/disable", headers=admin).status_code == 403
    r = env.client.put(f"/api/users/{boss.id}/role", json={"role": "MEMBER"}, headers=admin)
    assert r.status_code == 403
    assert env.user(f"boss@{DOMAIN}").role == UserRole.ADMIN


def test_the_last_admin_can_never_be_removed(env):
    """Unreachable through the API while admins can't act on themselves — which is exactly why
    it's worth a backstop: relax that one rule and this is what stops a total lock-out."""
    _admin(env)
    with env.db() as s:
        boss = s.scalars(select(m.User).where(m.User.email == f"boss@{DOMAIN}")).one()
        stranger = m.User(name="X", email=f"x@{DOMAIN}", status=UserStatus.ACTIVE)
        s.add(stranger)
        s.flush()
        with pytest.raises(access.AccessError, match="only active admin"):
            access.disable(s, boss, stranger)
        with pytest.raises(access.AccessError, match="only active admin"):
            access.change_role(s, boss, stranger, UserRole.MEMBER)


def test_members_cannot_see_or_run_the_team_page(env):
    admin = _admin(env)
    env.google(f"priya@{DOMAIN}")
    priya = env.user(f"priya@{DOMAIN}")
    env.client.post(f"/api/users/{priya.id}/approve", json={"role": "MEMBER"}, headers=admin)

    member = env.as_(f"priya@{DOMAIN}")
    assert env.client.get("/api/users", headers=member).status_code == 403
    assert env.client.get("/api/users/pending-count", headers=member).status_code == 403


def test_a_recycled_address_does_not_inherit_access(env):
    """Workspace can hand an ex-employee's address to someone new. New Google account, new
    `sub` — the old person's approval must not transfer."""
    _admin(env)
    env.google(f"priya@{DOMAIN}")
    with env.db() as s:
        u = s.scalars(select(m.User).where(m.User.email == f"priya@{DOMAIN}")).one()
        u.google_sub = "the-original-priya"
        u.status = UserStatus.ACTIVE
        s.commit()
    assert env.google(f"priya@{DOMAIN}").status_code == 403


def test_team_list_puts_waiting_requests_first(env):
    admin = _admin(env)
    env.google(f"a@{DOMAIN}")
    rows = env.client.get("/api/users", headers=admin).json()
    assert rows[0]["email"] == f"a@{DOMAIN}" and rows[0]["status"] == "PENDING"
    assert rows[0]["google_linked"] is True
    assert env.client.get("/api/users/pending-count", headers=admin).json() == {"count": 1}


# --------------------------------------------------------------------------- passwords
def test_passwords_are_optional_and_changing_one_needs_the_old_one(env):
    _admin(env)
    boss = env.as_(f"boss@{DOMAIN}")
    short = env.client.post("/api/auth/password", json={"new_password": "short"}, headers=boss)
    assert short.status_code == 422

    first = env.client.post("/api/auth/password", json={"new_password": "first password!"},
                            headers=boss)
    assert first.status_code == 200
    boss = {"Authorization": f"Bearer {first.json()['access_token']}"}

    wrong = env.client.post("/api/auth/password",
                            json={"current_password": "nope", "new_password": "second password!"},
                            headers=boss)
    assert wrong.status_code == 403

    login = env.client.post("/api/auth/login",
                            json={"email": f"boss@{DOMAIN}", "password": "first password!"})
    assert login.status_code == 200


def test_password_login_refuses_anyone_not_approved(env):
    with env.db() as s:
        s.add(m.User(name="W", email=f"w@{DOMAIN}", status=UserStatus.PENDING,
                     password_hash=hash_password("a long password")))
        s.commit()
    r = env.client.post("/api/auth/login", json={"email": f"w@{DOMAIN}", "password": "a long password"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid credentials"   # no hint that the account exists


# ------------------------------------------------------------------- the real Google path
def _real_google(monkeypatch, claims: dict | Exception):
    monkeypatch.setattr(settings, "google_auth_backend", "google")
    monkeypatch.setattr(settings, "google_client_id", "client-123.apps.googleusercontent.com")

    def fake_verify(token, request, audience=None, clock_skew_in_seconds=0):
        assert audience == "client-123.apps.googleusercontent.com"
        if isinstance(claims, Exception):
            raise claims
        return claims

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", fake_verify)


def _claims(**over):
    base = {"iss": "https://accounts.google.com", "sub": "1098", "email": f"priya@{DOMAIN}",
            "email_verified": True, "hd": DOMAIN, "name": "Priya Raman"}
    base.update(over)
    return base


def test_real_path_accepts_a_workspace_account(env, monkeypatch):
    _real_google(monkeypatch, _claims())
    assert env.client.post("/api/auth/google", json={"credential": "x"}).json()["status"] == "PENDING"


@pytest.mark.parametrize("over, why", [
    ({"hd": None}, "consumer Google account using a company address — no Workspace"),
    ({"hd": "othercompany.com"}, "someone else's Workspace"),
    ({"email_verified": False}, "Google hasn't confirmed they own the address"),
    ({"email": "priya@gmail.com", "hd": None}, "a personal account"),
])
def test_real_path_refuses_accounts_outside_our_workspace(env, monkeypatch, over, why):
    _real_google(monkeypatch, _claims(**over))
    assert env.client.post("/api/auth/google", json={"credential": "x"}).status_code == 403, why


def test_real_path_refuses_forged_or_foreign_tokens(env, monkeypatch):
    _real_google(monkeypatch, ValueError("Token has wrong audience"))
    assert env.client.post("/api/auth/google", json={"credential": "x"}).status_code == 401


def test_real_path_refuses_a_non_google_issuer(env, monkeypatch):
    _real_google(monkeypatch, _claims(iss="https://evil.example"))
    assert env.client.post("/api/auth/google", json={"credential": "x"}).status_code == 401


# ------------------------------------------------------------------------ configuration
def test_stub_sign_in_refuses_to_run_outside_local(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "google_auth_backend", "stub")
    with pytest.raises(RuntimeError, match="only allowed when"):
        settings.check_sign_in_config()


def test_production_refuses_the_development_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "google_auth_backend", "google")
    monkeypatch.setattr(settings, "google_client_id", "id")
    monkeypatch.setattr(settings, "jwt_secret", "dev-only-change-me-to-a-32char-plus-random-secret")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        settings.check_sign_in_config()
