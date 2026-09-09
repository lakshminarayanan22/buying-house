"""Retrieval chunks.

One row per slice of a document's text, with its embedding and a generated tsvector for the
lexical half of the hybrid search.

`company_id` and `deal_id` are denormalised from the parent document deliberately. They are
real foreign keys, which is what makes "brochures for companies in Tamil Nadu" a join rather
than a metadata-key match against a JSON blob — and the reason this is a hand-rolled table
instead of a vectorstore integration's own schema.
"""
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.models.base import Base, TimestampMixin, uuid_pk


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunk"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), index=True
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("deal.id", ondelete="CASCADE"), index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # What is shown to the user and cited. The text that was *embedded* has a context prefix
    # in front of it (see services/ingest.py) and is deliberately not stored — it is derivable.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dimensions))

    # Maintained by Postgres, so it can never fall out of step with `content`.
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )

    # Which backend produced `embedding`. A corpus embedded by two different models is not
    # comparable, and without this the only symptom is quietly worse retrieval.
    embedding_model: Mapped[str | None] = mapped_column(String(60))

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
        Index("ix_document_chunk_tsv", "content_tsv", postgresql_using="gin"),
    )
