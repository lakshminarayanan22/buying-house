"""In-memory SQLite with foreign keys and CHECK constraints live."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.models as m
from app.seed.taxonomy import seed_taxonomy


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    m.Base.metadata.create_all(engine)
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
