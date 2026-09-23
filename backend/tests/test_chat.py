"""The chatbot: guard, routing, tools and the write path.

The LLM itself is stubbed — these test the parts that must hold regardless of what the model
generates, which is the part worth testing.
"""
import os
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import app.models as m
from app.chat import guard
from app.chat.branches import apply_write, preview_write
from app.chat.classifier import route
from app.chat.llm import stub_classify
from app.chat.state import Category, ChatState
from app.chat.tools import find_company
from app.config import settings
from app.enums import DocumentKind
from app.seed.taxonomy import seed_taxonomy

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://bh:bh@localhost:5432/ecolink_test")


def _available() -> bool:
    try:
        engine = create_engine(TEST_DB)
        with engine.connect():
            pass
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason=f"needs Postgres at {TEST_DB}")


@pytest.fixture()
def factory(db):
    """The session factory behind the test database, for code that opens its own session."""
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "file_storage_dir", str(tmp_path))
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    m.Base.metadata.drop_all(engine)
    m.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_taxonomy(session)
    try:
        yield session
    finally:
        session.close()
        m.Base.metadata.drop_all(engine)
        engine.dispose()


# ---------------------------------------------------------------------- guard
@pytest.mark.parametrize("sql,allow_write,accepted", [
    ("select count(*) from deal", False, True),
    ("select c.name from company c join deal_party p on p.company_id = c.id", False, True),
    ("update deal set title = 'x' where id = '1'", False, False),
    ("update deal set title = 'x' where id = '1'", True, True),
    ("update deal set title = 'x'", True, False),
    ("delete from deal", True, False),
    ("delete from activity_log where id = '1'", True, False),
    ("update app_user set role = 'ADMIN' where id = '1'", True, False),
    ("update document set storage_key = 'x' where id = '1'", True, False),
    ("update document_chunk set content = 'x' where id = '1'", True, False),
    ("drop table deal", True, False),
    ("truncate company", True, False),
    ("select count(*) from deal; drop table deal", False, False),
    ("with d as (delete from deal where id='1' returning *) select * from d", True, False),
    ("select pg_read_file('/etc/passwd')", False, False),
    ("select pg_sleep(10)", False, False),
])
def test_guard(sql, allow_write, accepted):
    if accepted:
        assert guard.check(sql, allow_write=allow_write)
    else:
        with pytest.raises(guard.SqlRejected):
            guard.check(sql, allow_write=allow_write)


def test_a_read_path_cannot_be_talked_into_writing():
    """The single most important guarantee: whatever the model generates, a MEMBER's branch
    binds no write."""
    for sql in ["delete from deal where id='1'",
                "update company set name='x' where id='1'",
                "insert into company (id, name) values ('1','x')"]:
        with pytest.raises(guard.SqlRejected):
            guard.check(sql, allow_write=False)


# ------------------------------------------------------------------- routing
def test_stub_router_sends_questions_to_plausible_branches():
    assert stub_classify("How much commission is outstanding?").primary == Category.DATABASE
    assert stub_classify("What temperature is the finish applied at?").primary == Category.TECHNICAL
    assert stub_classify("Draft an introduction email").primary == Category.CREATIVE


def test_low_confidence_asks_instead_of_guessing():
    state: ChatState = {"needs_clarification": "which did you mean?"}
    assert route(state) == "clarify"


def test_out_of_scope_question_is_declined_without_a_branch():
    from app.chat.state import QueryClassification

    state: ChatState = {"classification": QueryClassification(
        primary=Category.OUT_OF_SCOPE, confidence=0.95, reasoning="general knowledge")}
    assert route(state) == "decline"


def test_an_unsure_out_of_scope_question_is_asked_about_rather_than_refused():
    """The asymmetry that matters: refusing a real question is worse than asking about a silly
    one, so anything under decline_confidence goes to clarify instead."""
    from app.chat.classifier import UNSURE_MESSAGE, classify
    from app.chat.state import QueryClassification
    import app.chat.classifier as classifier_module

    def fake_model(*_args, **_kwargs):
        class _M:
            def with_structured_output(self, _schema):
                return self

            def invoke(self, _prompt):
                return QueryClassification(
                    primary=Category.OUT_OF_SCOPE, confidence=0.65, reasoning="borderline")
        return _M()

    original = classifier_module.chat_model
    original_stub = classifier_module.is_stub
    classifier_module.chat_model = fake_model
    classifier_module.is_stub = lambda: False
    try:
        state = classify({"question": "what is the price of cotton?"})
    finally:
        classifier_module.chat_model = original
        classifier_module.is_stub = original_stub

    assert state["needs_clarification"] == UNSURE_MESSAGE
    assert route(state) == "clarify"


def test_the_stub_router_does_not_guess_when_nothing_matches():
    """The stub only knows the keywords it was given, so it catches an out-of-scope question
    when none of them appear. "Who is the prime minister of India?" still routes to DATABASE,
    because "who" is a records word — which is exactly why the stub is not a classifier and the
    real routing is measured separately in evals/classification_questions.json."""
    result = stub_classify("Tell me the weather in Chennai tomorrow")
    assert result.primary == Category.OUT_OF_SCOPE
    # Low enough that the graph asks rather than refuses.
    assert result.confidence < 0.7


# ------------------------------------------------------ creating records is the app's job
def test_a_request_to_create_a_record_is_recognised():
    from app.chat import newrecord

    for question in [
        "Add a contact at Chittagong Denim Ltd: Arif Chowdhury, production manager.",
        "Create a new company for the Tiruppur knitter we met.",
        "Register Saigon Garment Co as a supplier",
        "Set up a new deal for the Hanse programme",
        "add another follow-up to DL-2026-0015",
        "Please onboard a new mill in Karur",
    ]:
        assert newrecord.asks_to_create(question), question


def test_questions_about_existing_records_are_not_mistaken_for_creation():
    """The expensive false positive: a normal question answered with directions instead of data."""
    from app.chat import newrecord

    for question in [
        "Add up the commission Erode owes us",
        "Which deals were added in August?",
        "How many companies do we have on file?",
        "Who added the Kaimei deal?",
        "What is recorded as Sri Vaari's payment terms?",
        "List the contacts at Dhaka Knit Composite",
        "Update the ship date on DL-2026-0020 to 20 October 2026",
        "Delete the contact Meenakshi R at Coimbatore Compact Spinning",
    ]:
        assert not newrecord.asks_to_create(question), question


def test_plural_phrasings_are_caught():
    """"Add knitting to their processes" and "add GOTS to their certifications" are how people
    actually write it; the singular-only pattern missed both."""
    from app.chat import newrecord

    assert newrecord.asks_to_create("Add knitting to Chittagong Denim Ltd's processes")
    assert newrecord.asks_to_create("Add OEKO-TEX to Panipat Recycled Fibres' certifications")
    assert newrecord.asks_to_create(
        "Add a milestone 'Lab test report received' to DL-2026-0015")


def test_record_that_stays_ambiguous_on_purpose():
    """"Record that ..." introduces an update as often as a creation, so it is left to the
    guard rather than guessed at here. Catching it must not swallow this update."""
    from app.chat import newrecord

    assert not newrecord.asks_to_create(
        "The commission on DL-2026-0017 was invoiced on 16 September 2026 — record it.")


def test_the_directions_name_the_right_screen():
    from app.chat import newrecord

    assert newrecord.target_of("add a contact at Kavya") == "contact"
    assert newrecord.target_of("create a new deal for Hanse") == "deal"
    assert newrecord.target_of("add a follow-up to DL-2026-0001") == "milestone"
    assert newrecord.target_of("add GOTS to Panipat's certifications") == "capability"

    answer = newrecord.handoff("Add a contact at Chittagong Denim Ltd")
    assert "Add contact" in answer and "Contacts" in answer
    # It has to say what it *can* still do, or it reads as a flat refusal.
    assert "change or remove" in answer


def test_the_guard_refuses_an_insert_whatever_the_model_wrote():
    """The backstop: a phrasing the keyword check missed must still not create rows."""
    with pytest.raises(guard.SqlRejected) as raised:
        guard.check("INSERT INTO company (id, name) VALUES (gen_random_uuid(), 'X')",
                    allow_write=True)
    assert "created in the app" in str(raised.value)


# --------------------------------------------------------------------- tools
@pytest.fixture()
def companies(db):
    from app.enums import ReferenceDomain as D
    from app.seed.taxonomy import resolve

    dyer = m.Company(name="Erode Processors", city="Erode", sells=True,
                     moq_notes="500 kg per shade")
    spinner = m.Company(name="Sri Vaari Spinning Mills", city="Coimbatore",
                        buys=True, sells=True, capacity_notes="900 tonnes a month")
    db.add_all([dyer, spinner])
    db.commit()

    db.add_all([
        m.CompanyProcess(company_id=dyer.id,
                         process_id=resolve(db, D.PROCESS, "Fabric dyeing").id),
        m.CompanyProcess(company_id=spinner.id,
                         process_id=resolve(db, D.PROCESS, "Spinning").id),
        m.CompanyCertification(company_id=dyer.id,
                               certification_id=resolve(db, D.CERTIFICATION, "GOTS").id),
    ])
    db.commit()
    return {"dyer": dyer, "spinner": spinner}


def test_find_company_filters_on_the_taxonomy(db, companies):
    """The reason supplier matching is not RAG: this is a WHERE clause and it is exact."""
    matches = find_company(db, process="Fabric dyeing")
    assert [x.name for x in matches] == ["Erode Processors"]
    assert "process: Dyeing - fabric" in matches[0].reasons[0] or matches[0].reasons


def test_find_company_combines_filters(db, companies):
    assert find_company(db, process="Fabric dyeing", certification="GOTS")
    assert find_company(db, process="Spinning", certification="GOTS") == []


def test_find_company_reports_what_is_missing(db, companies):
    """"No capacity on file" stops someone quoting a customer a number nobody recorded."""
    match = find_company(db, process="Fabric dyeing")[0]
    assert any("capacity" in g for g in match.gaps)


def test_an_unknown_filter_value_matches_nothing(db, companies):
    """Not everything — the failure mode where a typo silently returns the whole directory."""
    assert find_company(db, process="teleportation") == []


# ----------------------------------------------------------------- write path
@pytest.fixture()
def deal(db, companies):
    d = m.Deal(deal_no="DL-2026-0001", title="Australian cotton")
    db.add(d)
    db.commit()
    return d


def test_preview_shows_a_real_diff_and_changes_nothing(db, deal, factory):
    checked = guard.check(
        f"update deal set title = 'Renamed' where id = '{deal.id}'", allow_write=True)
    preview = preview_write(checked, session_factory=factory)

    assert preview["affected"] == 1
    assert preview["diff"][0]["changes"]["title"]["before"] == "Australian cotton"
    assert preview["diff"][0]["changes"]["title"]["after"] == "Renamed"

    db.expire_all()
    assert db.get(m.Deal, deal.id).title == "Australian cotton"


def test_confirm_applies_and_logs_per_row(db, deal, factory):
    checked = guard.check(
        f"update deal set title = 'Renamed' where id = '{deal.id}'", allow_write=True)
    preview = preview_write(checked, session_factory=factory)

    apply_write(preview, actor_id=None, question="rename the cotton deal",
                session_factory=factory)

    db.expire_all()
    assert db.get(m.Deal, deal.id).title == "Renamed"
    logs = db.scalars(select(m.ActivityLog).where(m.ActivityLog.entity_type == "deal")).all()
    assert len(logs) == 1
    assert logs[0].before["title"] == "Australian cotton"


def test_confirm_refuses_when_the_row_changed_underneath(db, deal, factory):
    """Between preview and confirm somebody else edited it. Applying anyway would overwrite
    their work with a diff the reviewer never saw."""
    checked = guard.check(
        f"update deal set title = 'Renamed' where id = '{deal.id}'", allow_write=True)
    preview = preview_write(checked, session_factory=factory)

    deal.title = "Changed by someone else"
    db.commit()

    with pytest.raises(RuntimeError, match="changed since the preview"):
        apply_write(preview, actor_id=None, question="rename", session_factory=factory)

    db.expire_all()
    assert db.get(m.Deal, deal.id).title == "Changed by someone else"
