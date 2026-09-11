"""In-memory SQLite with foreign keys and CHECK constraints live."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.models as m
from app.seed.taxonomy import seed_taxonomy


@pytest.fixture(autouse=True)
def _offline_backends(monkeypatch):
    """Every test runs against the stub model and stub embeddings, whatever backend/.env says.

    Once a real VOYAGE_API_KEY went into .env, the retrieval tests started calling Voyage for
    real — spending tokens, depending on the network, and failing on the free tier's rate
    limit. A test that needs a real-looking backend fakes the client itself (see
    test_embedding.py) and sets the backend explicitly, which overrides this.
    """
    from app.config import settings
    monkeypatch.setattr(settings, "embedding_backend", "stub")
    monkeypatch.setattr(settings, "llm_backend", "stub")


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # document_chunk uses pgvector and tsvector, neither of which SQLite can compile. It is a
    # Postgres-only table by design and nothing in this file touches it — test_retrieval.py
    # covers it against real Postgres.
    sqlite_safe = [t for name, t in m.Base.metadata.tables.items() if name != "document_chunk"]
    m.Base.metadata.create_all(engine, tables=sqlite_safe)
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def taxonomy(db):
    seed_taxonomy(db)
    return True
