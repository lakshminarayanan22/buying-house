"""The taxonomy: one table, namespaced by domain.

Aliases are an array column rather than a second table. At this size the join bought nothing,
and "sinker" resolving to Single Jersey is still what makes search work when the person typing
is a merchandiser in a hurry.
"""
import uuid

from sqlalchemy import ARRAY, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, uuid_pk


class ReferenceItem(Base, TimestampMixin):
    __tablename__ = "reference_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    domain: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)

    # The words people actually type. Postgres text[] with a GIN index; on SQLite it degrades
    # to JSON, which the test suite is fine with.
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String).with_variant(__import__("sqlalchemy").JSON(), "sqlite"),
        nullable=False, default=list,
    )

    # Hierarchy where a domain needs it: Apparel -> Knitwear -> T-shirts.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notes: Mapped[str | None] = mapped_column(Text)

    parent: Mapped["ReferenceItem | None"] = relationship(remote_side=[id])

    __table_args__ = (
        UniqueConstraint("domain", "code", name="uq_reference_item_domain_code"),
        Index("ix_reference_item_domain_active", "domain", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Ref {self.domain}:{self.code}>"
