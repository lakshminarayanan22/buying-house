"""The taxonomy layer (§3): one namespaced table plus the alias table that makes matching work."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk


class ReferenceItem(Base, TimestampMixin):
    """A single taxonomy value, namespaced by `domain` (see enums.ReferenceDomain).

    `parent_id` gives hierarchy where a domain needs it — PRODUCT_CATEGORY is
    Apparel -> Knitwear -> T-shirts -> Polo. Flat domains simply leave it null.
    """

    __tablename__ = "reference_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    domain: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT"), index=True
    )
    # Materialised path ("APPAREL/KNITWEAR/TSHIRT") so a category filter can match a whole
    # subtree with a prefix scan instead of a recursive CTE on every directory query.
    path: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    parent: Mapped["ReferenceItem | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["ReferenceItem"]] = relationship(
        back_populates="parent", cascade="save-update"
    )
    aliases: Mapped[list["ReferenceAlias"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("domain", "code", name="uq_reference_item_domain_code"),
        # The target of every composite taxonomy FK — see models/base.reference_fk.
        UniqueConstraint("id", "domain", name="uq_reference_item_id_domain"),
        Index("ix_reference_item_domain_path", "domain", "path"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ReferenceItem {self.domain}:{self.code}>"


class ReferenceAlias(Base, TimestampMixin):
    """Synonyms for a taxonomy value.

    Suppliers say "Sinker", "Single Jersey" and "S/J" for one construction. Bulk import,
    the free-text "other" review queue, and Phase 6 tech-pack parsing all resolve through
    this table — §3: "the alias table is what saves you when you start matching text to
    taxonomy".
    """

    __tablename__ = "reference_alias"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(160), nullable=False)
    # Lowercased, punctuation-stripped form of `alias`; lookups hit this, never `alias`.
    normalised: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )

    item: Mapped[ReferenceItem] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("item_id", "normalised", name="uq_reference_alias_item_normalised"),
    )


class UnmappedTerm(Base, TimestampMixin):
    """The "other" escape hatch, as a review queue rather than a free-text graveyard.

    §11 names free-text capability data as the first thing that quietly kills the project.
    Users may always type something we don't know; that term lands here for a Super Admin to
    either map to an existing ReferenceItem (which writes a ReferenceAlias) or promote into a
    new one. Until resolved it is visible to internal staff and invisible to the matcher.
    """

    __tablename__ = "unmapped_term"

    id: Mapped[uuid.UUID] = uuid_pk()
    domain: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(String(300), nullable=False)
    normalised: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    source_entity_type: Mapped[str | None] = mapped_column(String(60))
    source_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))

    resolved_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="SET NULL")
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("domain", "normalised", name="uq_unmapped_term_domain_normalised"),
    )


def normalise_term(text: str) -> str:
    """Fold a user-typed term for alias lookup: casefold, collapse whitespace, drop punctuation."""
    import re

    cleaned = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return " ".join(cleaned.split())
