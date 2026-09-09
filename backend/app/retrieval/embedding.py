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
def _voyage(texts: list[str], *, is_query: bool) -> list[list[float]]:
    import voyageai

    if not settings.voyage_api_key:
        raise RuntimeError("EMBEDDING_BACKEND=voyage but VOYAGE_API_KEY is not set")

    client = voyageai.Client(api_key=settings.voyage_api_key)
    # Voyage distinguishes the two sides of the search. Embedding a question the same way as a
    # passage measurably hurts retrieval, and it is a one-word mistake to make.
    result = client.embed(
        texts, model=settings.embedding_model,
        input_type="query" if is_query else "document",
    )
    return result.embeddings


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
