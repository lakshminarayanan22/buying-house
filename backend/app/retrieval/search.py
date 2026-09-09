"""Hybrid retrieval: vector similarity fused with keyword rank.

Vector search alone is weak on exactly the tokens this domain runs on — GOTS, OEKO-TEX, Kaimei,
count numbers, product codes. A rare proper noun is a small part of a sentence embedding and a
decisive part of a lexical match. Reciprocal Rank Fusion combines the two ranks without needing
the two scores to be on a comparable scale, which they are not.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.retrieval.embedding import embed_one

# The constant in RRF. 60 is the value from the original paper and is not worth tuning before
# there is an eval set to tune it against.
RRF_K = 60

# Longest query we will turn into lexemes. A pathological paste should not build a 500-term
# tsquery.
MAX_QUERY_TERMS = 24


def _or_tsquery(query: str) -> str:
    """Turn a question into an OR tsquery.

    `plainto_tsquery` ANDs every term, which is close to useless on natural questions: "Kaimei
    cooling finish temperature" required all four words, and the brochure says "150 degrees
    celsius" rather than "temperature", so it matched nothing. The keyword half of a hybrid
    search should be high-recall and let ts_rank and RRF decide the order.

    Terms are sanitised to bare alphanumerics because `to_tsquery` is a parser and will raise on
    stray punctuation — the input here is a user's sentence, not a query language.
    """
    terms = []
    for raw in re.split(r"[^A-Za-z0-9]+", query.lower()):
        if len(raw) > 1 and raw not in terms:
            terms.append(raw)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    return " | ".join(terms)


@dataclass
class Hit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    chunk_index: int
    content: str
    similarity: float
    company_id: uuid.UUID | None
    deal_id: uuid.UUID | None
    matched_by: str          # "both" | "semantic" | "keyword"

    @property
    def citation(self) -> str:
        return f"{self.document_title} #{self.chunk_index}"


_SQL = text("""
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:qvec AS vector)) AS rank
    FROM document_chunk
    WHERE embedding IS NOT NULL
      AND (CAST(:company_id AS uuid) IS NULL OR company_id = CAST(:company_id AS uuid))
      AND (CAST(:deal_id    AS uuid) IS NULL OR deal_id    = CAST(:deal_id    AS uuid))
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT :pool
),
keyword AS (
    SELECT id, ROW_NUMBER() OVER (
               ORDER BY ts_rank(content_tsv, to_tsquery('english', :tsq)) DESC) AS rank
    FROM document_chunk
    WHERE content_tsv @@ to_tsquery('english', :tsq)
      AND (CAST(:company_id AS uuid) IS NULL OR company_id = CAST(:company_id AS uuid))
      AND (CAST(:deal_id    AS uuid) IS NULL OR deal_id    = CAST(:deal_id    AS uuid))
    LIMIT :pool
)
SELECT c.id, c.document_id, d.title, c.chunk_index, c.content,
       c.company_id, c.deal_id,
       1 - (c.embedding <=> CAST(:qvec AS vector)) AS similarity,
       s.id IS NOT NULL AS in_semantic,
       k.id IS NOT NULL AS in_keyword,
       (1.0 / (:rrf_k + COALESCE(s.rank, 1000000))
        + 1.0 / (:rrf_k + COALESCE(k.rank, 1000000))) AS fused
FROM document_chunk c
JOIN document d ON d.id = c.document_id
LEFT JOIN semantic s ON s.id = c.id
LEFT JOIN keyword  k ON k.id = c.id
WHERE s.id IS NOT NULL OR k.id IS NOT NULL
ORDER BY fused DESC
LIMIT :top_k
""")


def search(
    db: Session,
    query: str,
    *,
    top_k: int | None = None,
    company_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
    floor: float | None = None,
) -> list[Hit]:
    """Retrieve chunks for a question, filtered and fused.

    `floor` drops results whose *semantic* similarity is too low to be trusted. It is applied
    after fusion rather than inside it, so a strong keyword hit on a rare term survives even
    when the sentence embedding is unimpressed — which is the case RRF exists for.
    """
    if not query or not query.strip():
        return []

    top_k = top_k or settings.retrieval_top_k
    floor = settings.similarity_floor if floor is None else floor

    tsq = _or_tsquery(query)
    if not tsq:
        # Nothing lexically searchable — a query of punctuation or single letters. An empty
        # tsquery would make to_tsquery raise, so fall back to a term that matches nothing.
        tsq = "zzzznomatchzzzz"

    rows = db.execute(_SQL, {
        "qvec": str(embed_one(query, is_query=True)),
        "tsq": tsq,
        "company_id": str(company_id) if company_id else None,
        "deal_id": str(deal_id) if deal_id else None,
        "pool": max(20, top_k * 3),
        "top_k": top_k,
        "rrf_k": RRF_K,
    }).all()

    hits = []
    for (cid, did, title, idx, content, co_id, dl_id,
         similarity, in_semantic, in_keyword, _fused) in rows:
        similarity = float(similarity) if similarity is not None else 0.0
        if in_semantic and not in_keyword and similarity < floor:
            continue
        hits.append(Hit(
            chunk_id=cid, document_id=did, document_title=title, chunk_index=idx,
            content=content, similarity=similarity, company_id=co_id, deal_id=dl_id,
            matched_by="both" if in_semantic and in_keyword
                       else "semantic" if in_semantic else "keyword",
        ))
    return hits
