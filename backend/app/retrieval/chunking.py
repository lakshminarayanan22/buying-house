"""Turning a document's text into chunks worth embedding."""
from __future__ import annotations

import re

from app.config import settings

# Rough enough for chunk sizing. Counting real tokens would mean pulling in a tokeniser for a
# number that only decides where to split a paragraph.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def split_text(text: str, *, size_tokens: int | None = None,
               overlap_tokens: int | None = None) -> list[str]:
    """Split on the largest natural boundary that fits, falling back to smaller ones.

    Paragraphs first, then lines, then sentences, then a hard character cut. A brochure's
    "Machinery" section stays intact this way, which is what makes the chunk answerable on its
    own.
    """
    size = (size_tokens or settings.chunk_size_tokens) * CHARS_PER_TOKEN
    overlap = (overlap_tokens or settings.chunk_overlap_tokens) * CHARS_PER_TOKEN

    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    pieces = _split_recursive(text, size, ["\n\n", "\n", ". ", " "])

    # Re-join adjacent pieces up to the size limit, carrying an overlap so a fact split across
    # a boundary still appears whole in one of the two chunks.
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > size:
            chunks.append(current.strip())
            tail = current[-overlap:] if overlap else ""
            # Start the carry-over at a word boundary rather than mid-word.
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1:]
            current = f"{tail} {piece}".strip()
        else:
            current = f"{current} {piece}".strip() if current else piece

    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c.strip()]


def _split_recursive(text: str, size: int, separators: list[str]) -> list[str]:
    if len(text) <= size or not separators:
        return [text]

    separator, rest = separators[0], separators[1:]
    parts = text.split(separator)
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        out.extend([part] if len(part) <= size else _split_recursive(part, size, rest))
    return out


def context_prefix(document_title: str, company_name: str | None = None,
                   company_city: str | None = None, *, deal_no: str | None = None,
                   deal_title: str | None = None) -> str:
    """The line prepended before embedding — the highest-leverage part of ingestion.

    "Minimum order quantity 500 kg, lead time 12 days" is nearly identical across every brochure
    in the corpus. Embedded bare, retrieval cannot tell Erode from Tiruppur; a question naming a
    company matches every company equally. The prefix is not stored on the chunk — only what
    the user sees is — because it is derivable and would otherwise be shown in citations.
    """
    parts = [f"Document: {document_title}"]
    where = ", ".join(p for p in [company_name, company_city] if p)
    if where:
        parts.append(f"Company: {where}")
    if deal_no or deal_title:
        parts.append(f"Deal: {' — '.join(p for p in [deal_no, deal_title] if p)}")
    return " | ".join(parts)
