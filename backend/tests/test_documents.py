"""Filing a document, and removing one filed by mistake."""
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models as m
from app.auth import create_session_token
from app.config import settings
from app.db import get_db
from app.enums import ActivityAction, UserStatus
from app.main import app


@pytest.fixture()
def env(monkeypatch, tmp_path):
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
    monkeypatch.setattr(settings, "file_storage_dir", str(tmp_path))
    # Indexing runs after the response on its own session, against the real database. Not this
    # test's business, and it would reach outside the fixture.
    monkeypatch.setattr("app.api.documents._ingest_later", lambda document_id: None)

    with Session(engine, expire_on_commit=False) as s:
        user = m.User(name="Priya", email="priya@ecolinksolutions.in", status=UserStatus.ACTIVE)
        deal = m.Deal(deal_no="DL-2026-0001", title="Australian cotton")
        s.add_all([user, deal])
        s.commit()
        token = create_session_token(user.id, user.token_version)
        deal_id = str(deal.id)

    class Env:
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}
        root = tmp_path
        deal = deal_id

        @staticmethod
        def upload(content: bytes, name: str):
            return Env.client.post(
                "/api/documents",
                files={"file": (name, content, "text/plain")},
                data={"deal_id": deal_id, "kind": "PURCHASE_ORDER", "title": name},
                headers=Env.headers)

        @staticmethod
        def folder():
            return Env.client.get("/api/documents", params={"deal_id": deal_id},
                                  headers=Env.headers).json()

        @staticmethod
        def files():
            return sorted(p.name for p in pathlib.Path(tmp_path).rglob("*") if p.is_file())

        @staticmethod
        def db():
            return Session(engine, expire_on_commit=False)

    yield Env
    app.dependency_overrides.clear()
    engine.dispose()


def test_a_wrongly_filed_document_can_be_removed(env):
    doc = env.upload(b"wrong purchase order", "wrong.txt").json()
    assert len(env.folder()) == 1 and len(env.files()) == 1

    assert env.client.delete(f"/api/documents/{doc['id']}", headers=env.headers).status_code == 200
    assert env.folder() == []
    assert env.files() == []           # the file itself is gone, not just the listing


def test_the_deletion_is_recorded_even_though_the_file_is_not(env):
    doc = env.upload(b"an invoice", "invoice.txt").json()
    env.client.delete(f"/api/documents/{doc['id']}", headers=env.headers)

    with env.db() as s:
        log = s.scalars(select(m.ActivityLog).where(
            m.ActivityLog.action == ActivityAction.DELETE)).one()
        assert log.summary == "Deleted invoice.txt"
        assert log.actor_label == "Priya"
        assert str(log.deal_id) == env.deal      # "where did that invoice go" stays answerable


def test_deleting_one_copy_leaves_the_other_downloadable(env):
    """Stored names are a content hash, so the same file filed twice shares one file on disk.
    Deleting one copy must not break the other."""
    first = env.upload(b"identical bytes", "po.txt").json()
    second = env.upload(b"identical bytes", "po-again.txt").json()
    assert len(env.files()) == 1                  # one file, two rows

    env.client.delete(f"/api/documents/{first['id']}", headers=env.headers)

    assert len(env.files()) == 1                  # kept: the second row still points at it
    download = env.client.get(f"/api/documents/{second['id']}/download", headers=env.headers)
    assert download.status_code == 200 and download.content == b"identical bytes"

    env.client.delete(f"/api/documents/{second['id']}", headers=env.headers)
    assert env.files() == []                      # last one out removes the file


def test_deleting_something_that_is_not_there(env):
    import uuid
    gone = env.client.delete(f"/api/documents/{uuid.uuid4()}", headers=env.headers)
    assert gone.status_code == 404


def test_signed_out_visitors_cannot_delete(env):
    doc = env.upload(b"private", "private.txt").json()
    assert env.client.delete(f"/api/documents/{doc['id']}").status_code == 401
    assert len(env.folder()) == 1
