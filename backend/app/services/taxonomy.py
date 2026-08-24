"""Resolving user-typed text to taxonomy values (§3, §11).

The alias table is what makes bulk import and assisted onboarding survivable: a merchandiser
pastes a column that says "S/J" and it has to land on SINGLE_JERSEY. When it does not, the
term goes to a review queue instead of into a free-text field, because "we do all kinds of
knits" is unmatchable and unmatchable data is invisible to the agent.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ReferenceDomain
from app.models import ReferenceAlias, ReferenceItem, UnmappedTerm, normalise_term


def resolve(
    db: Session, domain: ReferenceDomain, text: str
) -> ReferenceItem | None:
    """Find the taxonomy value a piece of text refers to.

    Three passes, cheapest first: exact code, exact name, then alias. No fuzzy matching — a
    near-miss that silently resolves to the wrong construction is worse than an unresolved
    term a human looks at.
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()
    normalised = normalise_term(cleaned)

    exact = db.scalars(
        select(ReferenceItem).where(
            ReferenceItem.domain == domain,
            ReferenceItem.is_active.is_(True),
            func.lower(ReferenceItem.code) == cleaned.lower(),
        )
    ).first()
    if exact:
        return exact

    by_name = db.scalars(
        select(ReferenceItem).where(
            ReferenceItem.domain == domain,
            ReferenceItem.is_active.is_(True),
            func.lower(ReferenceItem.name) == cleaned.lower(),
        )
    ).first()
    if by_name:
        return by_name

    by_alias = db.scalars(
        select(ReferenceItem)
        .join(ReferenceAlias, ReferenceAlias.item_id == ReferenceItem.id)
        .where(
            ReferenceItem.domain == domain,
            ReferenceItem.is_active.is_(True),
            ReferenceAlias.normalised == normalised,
        )
    ).first()
    return by_alias


def resolve_or_queue(
    db: Session,
    domain: ReferenceDomain,
    text: str,
    *,
    source_entity_type: str | None = None,
    source_entity_id: uuid.UUID | None = None,
) -> ReferenceItem | None:
    """Resolve, or record the miss for a Super Admin to map.

    Repeated misses increment `occurrences` rather than piling up duplicate rows, which turns
    the queue into a ranked to-do list: the term forty suppliers typed gets mapped first.
    """
    item = resolve(db, domain, text)
    if item is not None:
        return item

    normalised = normalise_term(text)
    if not normalised:
        return None

    existing = db.scalars(
        select(UnmappedTerm).where(
            UnmappedTerm.domain == domain, UnmappedTerm.normalised == normalised
        )
    ).first()
    if existing is not None:
        existing.occurrences += 1
        return None

    db.add(
        UnmappedTerm(
            domain=domain,
            raw_text=text.strip()[:300],
            normalised=normalised,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
        )
    )
    return None


def add_alias(db: Session, item: ReferenceItem, alias: str, language: str = "en") -> ReferenceAlias:
    """Teach the taxonomy a synonym. Idempotent, so re-running a seed is safe.

    Two different spellings can fold to the same normalised form ("Ex Works" and "ex-works"),
    so the new row is flushed immediately: with autoflush off, an unflushed sibling is
    invisible to the duplicate check and the pair would collide on the unique constraint.
    """
    normalised = normalise_term(alias)
    existing = db.scalars(
        select(ReferenceAlias).where(
            ReferenceAlias.item_id == item.id, ReferenceAlias.normalised == normalised
        )
    ).first()
    if existing is not None:
        return existing

    row = ReferenceAlias(
        item_id=item.id, alias=alias.strip(), normalised=normalised, language=language
    )
    db.add(row)
    db.flush()
    return row


def resolve_unmapped(
    db: Session, term: UnmappedTerm, item: ReferenceItem, resolved_by_user_id: uuid.UUID | None
) -> ReferenceAlias:
    """Map a queued term onto an existing value, which teaches the alias table permanently."""
    from datetime import datetime, timezone

    alias = add_alias(db, item, term.raw_text)
    term.resolved_item_id = item.id
    term.resolved_by_user_id = resolved_by_user_id
    term.resolved_at = datetime.now(timezone.utc)
    return alias


def build_path(db: Session, item: ReferenceItem) -> str:
    """Materialise the ancestry path used for subtree filters ("APPAREL/KNITWEAR/TSHIRT")."""
    codes = [item.code]
    parent_id = item.parent_id
    seen: set[uuid.UUID] = set()

    while parent_id is not None and parent_id not in seen:
        seen.add(parent_id)
        parent = db.get(ReferenceItem, parent_id)
        if parent is None:
            break
        codes.append(parent.code)
        parent_id = parent.parent_id

    return "/".join(reversed(codes))


def refresh_path(db: Session, item: ReferenceItem) -> None:
    """Recompute path/depth for an item and everything beneath it after a re-parent."""
    item.path = build_path(db, item)
    item.depth = item.path.count("/")

    children = db.scalars(select(ReferenceItem).where(ReferenceItem.parent_id == item.id)).all()
    for child in children:
        refresh_path(db, child)


def descendants_filter(item: ReferenceItem):
    """A clause matching an item and everything under it — one prefix scan, no recursive CTE."""
    return (ReferenceItem.id == item.id) | ReferenceItem.path.like(f"{item.path}/%")
