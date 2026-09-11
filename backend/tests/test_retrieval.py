"""The retrieval layer, against real Postgres.

pgvector, tsvector and the RRF query are all Postgres features; testing them on SQLite would
test something else entirely.
"""
import importlib
import os
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.models as m
from app.config import settings
from app.enums import DocumentKind, ExtractionStatus
from app.retrieval import search
from app.retrieval.chunking import context_prefix, split_text
from app.retrieval.embedding import embed_one
from app.services.ingest import extract_text, ingest_document

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://bh:bh@localhost:5432/ecolink_test"
)


def _available() -> bool:
    try:
        engine = create_engine(TEST_DB)
        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM pg_available_extensions WHERE name='vector'")).first()
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _available(), reason=f"needs Postgres with pgvector at {TEST_DB}"
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "file_storage_dir", str(tmp_path))
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    m.Base.metadata.drop_all(engine)
    m.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        m.Base.metadata.drop_all(engine)
        engine.dispose()


def _document(db, tmp_path, title, body, company=None, kind=DocumentKind.BROCHURE):
    key = f"{uuid.uuid4().hex}.txt"
    (pathlib.Path(settings.file_storage_dir) / key).write_text(body)
    doc = m.Document(
        title=title, storage_key=key, kind=kind, content_type="text/plain",
        company_id=company.id if company else None,
    )
    db.add(doc)
    db.commit()
    return doc


@pytest.fixture()
def corpus(db, tmp_path):
    kovai = m.Company(name="Kovai Knits", city="Tiruppur")
    erode = m.Company(name="Erode Processors", city="Erode")
    db.add_all([kovai, erode])
    db.commit()

    _document(db, tmp_path, "Kovai Knits profile", """
        Kovai Knits Private Limited, Tiruppur.
        Machinery: 24 Mayer and Cie sinker circular knitting machines, 30 inch diameter.
        Minimum order quantity 1000 pieces. Lead time 45 days.
        Certifications held: GOTS and OEKO-TEX Standard 100.
        """, company=kovai)
    _document(db, tmp_path, "Erode Processors profile", """
        Erode Processors Private Limited, Erode.
        Machinery: 12 soft flow dyeing machines, 3 stenters, 4 compactors.
        Minimum order quantity 500 kilograms per shade. Lead time 21 days.
        We apply the Kaimei cooling finish under licence.
        """, company=erode)

    for doc in db.scalars(select(m.Document)).all():
        ingest_document(db, doc.id)
    return {"kovai": kovai, "erode": erode}


# ------------------------------------------------------------------- chunking
def test_short_text_is_one_chunk():
    assert len(split_text("Kovai Knits runs 24 machines.")) == 1


def test_long_text_splits_with_overlap():
    body = "Sentence about knitting machines. " * 300
    chunks = split_text(body)
    assert len(chunks) > 1
    assert all(len(c) <= settings.chunk_size_tokens * 4 + 200 for c in chunks)


def test_context_prefix_names_the_company():
    """A bare 'MOQ 500 kg' chunk is identical across brochures; the prefix is what separates
    Erode from Tiruppur at retrieval time."""
    prefix = context_prefix("Erode profile", "Erode Processors", "Erode")
    assert "Erode Processors" in prefix and "Erode" in prefix


# ------------------------------------------------------------------ ingestion
def test_ingestion_writes_chunks_and_marks_ok(db, corpus):
    docs = db.scalars(select(m.Document)).all()
    assert all(d.extraction_status == ExtractionStatus.OK for d in docs)
    assert all(d.extracted_text for d in docs)
    assert db.scalar(select(func.count(m.DocumentChunk.id))) > 0


def test_chunks_carry_the_company_for_filtering(db, corpus):
    """The foreign key is the reason this is a hand-rolled table — it makes a company filter a
    join rather than a JSON metadata match."""
    chunks = db.scalars(
        select(m.DocumentChunk).where(m.DocumentChunk.company_id == corpus["kovai"].id)
    ).all()
    assert chunks and all("Kovai" in c.content or "Mayer" in c.content for c in chunks)


def test_reingest_replaces_rather_than_accumulates(db, corpus, tmp_path):
    doc = db.scalars(select(m.Document)).first()
    before = db.scalar(
        select(func.count(m.DocumentChunk.id)).where(m.DocumentChunk.document_id == doc.id))
    ingest_document(db, doc.id)
    after = db.scalar(
        select(func.count(m.DocumentChunk.id)).where(m.DocumentChunk.document_id == doc.id))
    assert before == after


def test_a_scanned_pdf_is_flagged_for_ocr(db, tmp_path):
    """The failure mode this prevents: a brochure that indexes as an empty string and turns
    into a chatbot that confidently does not know things."""
    import pymupdf

    company = m.Company(name="Scanned Mills", city="Salem")
    db.add(company)
    db.commit()

    key = "scan.pdf"
    pdf = pymupdf.open()
    pdf.new_page()                      # a page with no text layer — what a scan looks like
    pdf.save(pathlib.Path(settings.file_storage_dir) / key)
    pdf.close()

    doc = m.Document(title="Scanned brochure", storage_key=key, kind=DocumentKind.BROCHURE,
                     content_type="application/pdf", company_id=company.id)
    db.add(doc)
    db.commit()

    result = ingest_document(db, doc.id)
    db.refresh(doc)
    assert doc.extraction_status == ExtractionStatus.NEEDS_OCR
    assert result["chunks"] == 0


def test_a_short_text_document_is_still_indexed(db, tmp_path):
    """A real purchase order is three lines long. An earlier version held every file to the
    PDF scan-detection threshold and silently skipped exactly the short documents a deal
    folder is full of."""
    company = m.Company(name="Short Doc Mills", city="Tiruppur")
    db.add(company)
    db.commit()
    doc = _document(db, tmp_path, "PO 4471",
                    "PURCHASE ORDER 4471\nQuantity 240 MT.\nFOB Brisbane.", company=company)
    result = ingest_document(db, doc.id)
    db.refresh(doc)
    assert doc.extraction_status == ExtractionStatus.OK
    assert result["chunks"] == 1


def test_a_deal_document_carries_the_deal_in_its_prefix():
    """A PO filed under a deal has no company of its own; without the deal in the prefix it has
    nothing to match on but the word "purchase"."""
    prefix = context_prefix("PO 4471", deal_no="DL-2026-0001", deal_title="Australian cotton")
    assert "DL-2026-0001" in prefix and "Australian cotton" in prefix


def test_an_empty_text_file_is_skipped_not_indexed(db, tmp_path):
    """Empty is not the same as scanned — OCR would not help, so it reports differently."""
    company = m.Company(name="Empty Mills", city="Karur")
    db.add(company)
    db.commit()
    doc = _document(db, tmp_path, "Blank note", "   ", company=company)
    result = ingest_document(db, doc.id)
    db.refresh(doc)
    assert doc.extraction_status == ExtractionStatus.SKIPPED
    assert result["chunks"] == 0


def test_a_missing_file_is_recorded_not_raised(db, tmp_path):
    company = m.Company(name="Ghost Mills", city="Erode")
    db.add(company)
    db.commit()
    doc = m.Document(title="Ghost", storage_key="nope/missing.pdf",
                     kind=DocumentKind.OTHER, company_id=company.id)
    db.add(doc)
    db.commit()
    ingest_document(db, doc.id)
    db.refresh(doc)
    assert doc.extraction_status == ExtractionStatus.FAILED
    assert "FileNotFoundError" in doc.extraction_error


def test_deleting_a_document_takes_its_chunks(db, corpus):
    doc = db.scalars(select(m.Document)).first()
    db.delete(doc)
    db.commit()
    orphans = db.scalar(
        select(func.count(m.DocumentChunk.id)).where(m.DocumentChunk.document_id == doc.id))
    assert orphans == 0


# ------------------------------------------------------------------- search
def test_keyword_terms_are_ored_not_anded(db, corpus):
    """The bug this locks down: plainto_tsquery ANDs every term, so "Kaimei cooling finish
    temperature" required all four and matched nothing — the brochure says "150 degrees
    celsius", never "temperature". The keyword half must be high recall."""
    from app.retrieval.search import _or_tsquery

    assert _or_tsquery("Kaimei cooling finish temperature") == (
        "kaimei | cooling | finish | temperature")

    hits = search(db, "Kaimei cooling finish temperature")
    assert hits, "a question whose words only partly appear must still retrieve"
    assert any("Kaimei" in h.content for h in hits)


def test_a_query_with_no_usable_terms_does_not_raise(db, corpus):
    """to_tsquery is a parser and raises on empty or malformed input; the caller here is a
    user's sentence, so it has to be sanitised rather than trusted."""
    assert search(db, "?!?") == []


def test_keyword_half_finds_a_rare_proper_noun(db, corpus):
    """The reason for hybrid search: 'Kaimei' is one token in one brochure. A sentence
    embedding barely registers it; a lexical match is decisive."""
    hits = search(db, "Kaimei cooling finish")
    assert hits
    assert any("Kaimei" in h.content for h in hits)
    assert any(h.matched_by in {"keyword", "both"} for h in hits)


def test_company_filter_restricts_results(db, corpus):
    hits = search(db, "minimum order quantity", company_id=corpus["erode"].id)
    assert hits
    assert all(h.company_id == corpus["erode"].id for h in hits)


def test_search_returns_citations(db, corpus):
    hits = search(db, "sinker machines")
    assert hits
    assert hits[0].citation.startswith("Kovai Knits profile #")


def test_search_survives_the_embedding_service_failing(db, corpus, monkeypatch):
    """Voyage throttled or unreachable: the question still gets its keyword matches."""
    def down(*_a, **_k):
        raise RuntimeError("429 rate limited")
    # `app.retrieval.search` names the function once the package is imported; patch the module.
    monkeypatch.setattr(importlib.import_module("app.retrieval.search"), "embed_one", down)

    hits = search(db, "sinker machines")
    assert hits and hits[0].citation.startswith("Kovai Knits profile #")
    assert all(h.matched_by == "keyword" for h in hits)


def test_empty_query_returns_nothing(db, corpus):
    assert search(db, "   ") == []


def test_no_match_returns_nothing(db, corpus):
    """A question the corpus cannot answer must come back empty so the branch can refuse
    rather than reason from an empty context."""
    assert search(db, "zzzzqqq nonexistent unrelated term", floor=0.99) == []
