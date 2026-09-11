"""Rebuild every document's chunks from scratch.

Run after changing chunk size, the context prefix, or the embedding model. Without this those
are frightening changes; with it they are routine.

    python -m scripts.reindex             # everything
    python -m scripts.reindex --missing   # only documents never processed
    python -m scripts.reindex --stale     # only documents not yet on the current model —
                                          # resumes an interrupted switch of embedding model
"""
import argparse
import logging
import sys

from app.config import settings
from app.db import SessionLocal
from app.retrieval.embedding import active_model
from app.services.ingest import reindex_all

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("reindex")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing", action="store_true",
                        help="only documents still marked PENDING")
    parser.add_argument("--stale", action="store_true",
                        help="only documents with chunks from a different embedding model")
    args = parser.parse_args()

    log.info("embedding backend: %s (%s, %s dims)",
             settings.embedding_backend, active_model(), settings.embedding_dimensions)
    if settings.embedding_backend == "stub":
        log.warning("STUB BACKEND — vectors are deterministic hashes, not semantics. "
                    "Lexical search still works; semantic recall numbers are meaningless.")

    db = SessionLocal()
    try:
        totals = reindex_all(db, only_missing=args.missing, only_stale=args.stale)
    finally:
        db.close()

    log.info("%s documents, %s chunks", totals["documents"], totals["chunks"])
    for key, label in [("needs_ocr", "need OCR"), ("failed", "failed"), ("skipped", "skipped"),
                       ("embedding_failed", "couldn't be embedded (left as they were)")]:
        if totals[key]:
            log.info("  %s %s", totals[key], label)
    if totals["embedding_failed"]:
        log.info("Run again with --stale to retry just those.")
    return 1 if totals["failed"] or totals["embedding_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
