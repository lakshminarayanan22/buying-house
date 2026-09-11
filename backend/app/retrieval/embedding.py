"""Embeddings, behind one interface with three backends.

The backend is a config value because the choice is not settled: Voyage costs pennies but needs
a key; a local model needs neither but downloads a few hundred megabytes. The stub exists so the
rest of the pipeline — chunking, storage, the lexical half of hybrid search, the transaction
boundaries — can be built and tested before either of those is in place.

**The stub is not a retrieval model.** Its vectors are deterministic hashes; cosine similarity
between them is noise. Anything measuring semantic recall must run against `voyage` or `local`.
"""
from __future__ import annotations

import hashlib
import logging
import math

from app.config import settings

logger = logging.getLogger(__name__)


def active_model() -> str:
    """The identifier stored on every chunk, so a mixed-model corpus is detectable."""
    if settings.embedding_backend == "stub":
        return f"stub-{settings.embedding_dimensions}"
    return settings.embedding_model


# ------------------------------------------------------------------------- stub
def _stub_vector(text: str) -> list[float]:
    """A deterministic unit vector derived from the text.

    Same text in, same vector out, so tests are reproducible. Normalised so that the
    `1 - cosine_distance` arithmetic downstream behaves the same as it will with a real model.
    """
    dims = settings.embedding_dimensions
    out: list[float] = []
    counter = 0
    while len(out) < dims:
        digest = hashlib.sha256(f"{text}|{counter}".encode()).digest()
        out.extend((b - 127.5) / 127.5 for b in digest)
        counter += 1
    out = out[:dims]

    norm = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / norm for v in out]


# ----------------------------------------------------------------------- voyage
# 128 chunks of ~500 tokens is ~64K tokens a request: a fifth of Voyage's token cap, an eighth
# of its text cap.
VOYAGE_BATCH = 128


def _voyage(texts: list[str], *, is_query: bool) -> list[list[float]]:
    import voyageai

    if not settings.voyage_api_key:
        raise RuntimeError("EMBEDDING_BACKEND=voyage but VOYAGE_API_KEY is not set")

    client = voyageai.Client(api_key=settings.voyage_api_key)
    vectors: list[list[float]] = []
    # Voyage refuses a request over 1,000 texts, and caps its tokens too (320K on voyage-4).
    # A document's chunks all arrive here in one call, so a long brochure would be rejected
    # whole; batches of VOYAGE_BATCH keep every request far inside both limits.
    for start in range(0, len(texts), VOYAGE_BATCH):
        result = client.embed(
            texts[start:start + VOYAGE_BATCH], model=settings.embedding_model,
            # Voyage distinguishes the two sides of the search. Embedding a question the same
            # way as a passage measurably hurts retrieval, and it is a one-word mistake to make.
            input_type="query" if is_query else "document",
        )
        vectors.extend(result.embeddings)
    return vectors


# ------------------------------------------------------------------------ local
_local_model = None


def _local(texts: list[str]) -> list[list[float]]:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("loading local embedding model %s", settings.embedding_model)
        _local_model = SentenceTransformer(settings.embedding_model)

    vectors = _local_model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


# ---------------------------------------------------------------------- public
def embed_many(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    if not texts:
        return []

    backend = settings.embedding_backend
    if backend == "stub":
        return [_stub_vector(t) for t in texts]
    if backend == "voyage":
        return _voyage(texts, is_query=is_query)
    if backend == "local":
        return _local(texts)
    raise RuntimeError(f"unknown EMBEDDING_BACKEND {backend!r}")


def embed_one(text: str, *, is_query: bool = False) -> list[float]:
    return embed_many([text], is_query=is_query)[0]
