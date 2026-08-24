"""Polymorphic document store with validity dates and a verification decision per file."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import DocumentType, VerificationStatus
from app.models.base import Base, TimestampMixin, uuid_pk


class Document(Base, TimestampMixin):
    """One uploaded file, attached to any entity by (owner_type, owner_id).

    `valid_till` is the column the certificate-expiry sweep runs on (§5.3: reminders at
    T-60/30/7, badge dropped on expiry), so it lives here rather than only on the
    certification row — an audit report and a GST certificate expire too.

    org_id is denormalised onto every document so the access-control layer can scope file
    access with one predicate instead of resolving the owner entity first.
    """

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    owner_type: Mapped[str] = mapped_column(String(60), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))

    doc_type: Mapped[DocumentType] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(240))

    # S3/R2 object key. Files are served only through presigned URLs minted after an access
    # check — never by storing a public URL on the row.
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)

    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_till: Mapped[date | None] = mapped_column(Date, index=True)

    verification_status: Mapped[VerificationStatus] = mapped_column(
        String(20), nullable=False, default=VerificationStatus.PENDING,
        server_default=VerificationStatus.PENDING.value, index=True,
    )
    verification_notes: Mapped[str | None] = mapped_column(Text)
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Brand-facing visibility. Internal notes and audit findings stay internal by default;
    # a document becomes visible to the other side only by explicit decision.
    is_internal_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_document_owner", "owner_type", "owner_id"),
        Index("ix_document_expiry_sweep", "valid_till", "verification_status"),
    )

    @property
    def is_expired(self) -> bool:
        return self.valid_till is not None and self.valid_till < date.today()
