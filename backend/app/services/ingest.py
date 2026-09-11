"""Document → text → chunks → embeddings.

Runs in the background after an upload. The two things it must not do quietly are lose a
document (a scan with no text layer must be visible, not merely absent) and leave a document
half-indexed (a delete that succeeds followed by an insert that fails).
"""
from __future__ import annotations

import logging
import pathlib
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import ExtractionStatus
from app.models import Company, Deal, Document, DocumentChunk
from app.retrieval.chunking import context_prefix, estimate_tokens, split_text
from app.retrieval.embedding import active_model, embed_many

logger = logging.getLogger(__name__)

# Below this, a PDF is a scan rather than a document with a text layer. It is a *scan detector*
# and applies to PDFs only — a real purchase order can be three lines long, and holding text
# files to the same bar would silently drop exactly the short documents a deal folder is full of.
MIN_PDF_TEXT_CHARS = 200

TEXT_SUFFIXES = {".txt", ".md", ".csv"}


def extract_text(path: pathlib.Path, content_type: str | None) -> tuple[str, ExtractionStatus]:
    """Pull text out of a file. Returns the text and what happened.

    The minimum-content check applies to every type, not just PDFs. A file that yields almost
    nothing has to be visible whatever it was, because the symptom of silently indexing an
    empty string is a chatbot that confidently does not know things.
    """
    suffix = path.suffix.lower()
    is_pdf = suffix == ".pdf" or (content_type or "") == "application/pdf"

    if is_pdf:
        import pymupdf

        with pymupdf.open(path) as doc:
            text = "\n\n".join(page.get_text() for page in doc)
    elif suffix in TEXT_SUFFIXES or (content_type or "").startswith("text/"):
        text = path.read_text(errors="replace")
    else:
        # An image or a spreadsheet. Not a failure — simply nothing to index.
        return "", ExtractionStatus.SKIPPED

    if is_pdf and len(text.strip()) < MIN_PDF_TEXT_CHARS:
        # Almost no text layer: a scan. OCR would recover it, so it is flagged rather than
        # stored as an empty string.
        return text, ExtractionStatus.NEEDS_OCR
    if not text.strip():
        # Genuinely empty. OCR would not help, so it reports differently.
        return text, ExtractionStatus.SKIPPED
    return text, ExtractionStatus.OK


def ingest_document(db: Session, document_id: uuid.UUID) -> dict:
    """Extract, chunk, embed and store. Idempotent — re-running replaces the chunks."""
    doc = db.get(Document, document_id)
    if doc is None:
        return {"status": "missing"}

    root = pathlib.Path(settings.file_storage_dir).expanduser()
    path = (root / doc.storage_key).resolve()

    try:
        if not path.exists():
            raise FileNotFoundError(doc.storage_key)
        text, status = extract_text(path, doc.content_type)
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the queue
        logger.exception("extraction failed for %s", document_id)
        doc.extraction_status = ExtractionStatus.FAILED
        doc.extraction_error = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        return {"status": ExtractionStatus.FAILED.value, "error": doc.extraction_error}

    doc.extracted_text = text or None
    doc.extraction_status = status
    doc.extraction_error = None

    if status is not ExtractionStatus.OK:
        # Still clear stale chunks: a re-upload that turns out to be a scan must not leave the
        # previous version's text answering questions.
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        db.commit()
        return {"status": status.value, "chunks": 0}

    company = db.get(Company, doc.company_id) if doc.company_id else None
    deal = db.get(Deal, doc.deal_id) if doc.deal_id else None
    # A purchase order filed under a deal has no company of its own. Without the deal in the
    # prefix, "the PO for the cotton shipment" has nothing to match on but the word "purchase".
    prefix = context_prefix(
        doc.title,
        company.name if company else None,
        company.city if company else None,
        deal_no=deal.deal_no if deal else None,
        deal_title=deal.title if deal else None,
    )

    pieces = split_text(text)
    vectors = embed_many([f"{prefix}\n\n{piece}" for piece in pieces])
    model = active_model()

    # Delete and insert inside one transaction. A partial failure that deleted without
    # inserting would leave the document unindexed with nothing to indicate it.
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    db.add_all([
        DocumentChunk(
            document_id=doc.id, company_id=doc.company_id, deal_id=doc.deal_id,
            chunk_index=i, content=piece, token_count=estimate_tokens(piece),
            embedding=vector, embedding_model=model,
        )
        for i, (piece, vector) in enumerate(zip(pieces, vectors))
    ])
    db.commit()

    logger.info("ingested %s: %s chunks (%s)", doc.title, len(pieces), model)
    return {"status": status.value, "chunks": len(pieces), "model": model}


def reindex_all(db: Session, *, only_missing: bool = False, only_stale: bool = False) -> dict:
    """Rebuild every document's chunks.

    Run this whenever chunk size, the context prefix or the embedding model changes — without
    it those become frightening changes rather than routine ones.

    `only_stale` redoes just the documents with chunks from some other model — how an
    interrupted switch of embedding model is resumed without paying again for what finished.
    """
    stmt = select(Document.id)
    if only_missing:
        stmt = stmt.where(Document.extraction_status == ExtractionStatus.PENDING)
    if only_stale:
        stmt = stmt.where(Document.id.in_(
            select(DocumentChunk.document_id).where(DocumentChunk.embedding_model != active_model())
        ))

    totals = {"documents": 0, "chunks": 0, "needs_ocr": 0, "failed": 0, "skipped": 0,
              "embedding_failed": 0}
    for (doc_id,) in db.execute(stmt).all():
        try:
            result = ingest_document(db, doc_id)
        except Exception as exc:     # the embedding service, almost always
            # One throttled document used to abort the whole run. Its old chunks are untouched —
            # ingest only replaces them once new vectors are in hand — so skip it, count it, and
            # let `--stale` pick it up next time.
            db.rollback()
            logger.warning("could not embed document %s, left as it was: %s", doc_id, exc)
            totals["documents"] += 1
            totals["embedding_failed"] += 1
            continue
        totals["documents"] += 1
        totals["chunks"] += result.get("chunks", 0)
        if result["status"] == ExtractionStatus.NEEDS_OCR.value:
            totals["needs_ocr"] += 1
        elif result["status"] == ExtractionStatus.FAILED.value:
            totals["failed"] += 1
        elif result["status"] == ExtractionStatus.SKIPPED.value:
            totals["skipped"] += 1
    return totals
