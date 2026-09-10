"""Users, documents and the audit trail.

Only Ecolink staff use this, and only through an @ecolinksolutions.in Google account. Signing in
creates the account in PENDING; an admin approves it once. The user model is a name, an email,
one of two roles, and where the person is in that approval.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import ActivityAction, DocumentKind, ExtractionStatus, UserRole, UserStatus
from app.models.base import Base, JSONVariant, TimestampMixin, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(240), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    role: Mapped[UserRole] = mapped_column(
        String(16), nullable=False, default=UserRole.MEMBER, server_default=UserRole.MEMBER.value
    )
    # Optional. Google is how an account comes into being; a password is a second way into an
    # account that already exists and has been approved. Nobody can create an account with one.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[UserStatus] = mapped_column(
        String(16), nullable=False, default=UserStatus.PENDING,
        server_default=UserStatus.PENDING.value, index=True,
    )
    # Google's `sub` claim: the account's permanent id. Matched before the email, because an
    # address can be renamed inside Workspace and a sub never changes.
    google_sub: Mapped[str | None] = mapped_column(String(64))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The last access decision, and who made it. Null until an admin has acted — or for the
    # bootstrap admins named in config, who are let in by configuration rather than by a person.
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )

    # Bumped to invalidate every outstanding session for this user at once.
    token_version: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    __table_args__ = (
        UniqueConstraint("email", name="uq_app_user_email"),
        UniqueConstraint("google_sub", name="uq_app_user_google_sub"),
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'REJECTED', 'DISABLED')", name="status_known"
        ),
    )


class Document(Base, TimestampMixin):
    """A file, filed against a deal or a company.

    "For a particular deal it is better to group all the invoices, POs etc into one folder" —
    so a deal's folder is simply every document carrying its deal_id. A file can also hang off
    a company with no deal, which is where the factory brochure lives.

    Both foreign keys are nullable and at least one must be set; a document belonging to nothing
    is a file nobody will ever find again.
    """

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = uuid_pk()
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("deal.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[DocumentKind] = mapped_column(
        String(24), nullable=False, default=DocumentKind.OTHER,
        server_default=DocumentKind.OTHER.value, index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(300))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)

    # Text pulled out of the file. Empty today; it is where the factory brochure's contents will
    # sit when the chatbot needs something to retrieve over, and adding it now costs one column.
    extracted_text: Mapped[str | None] = mapped_column(Text)

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )

    # Where this file got to in the ingestion pipeline. NEEDS_OCR is the one that matters:
    # a scanned brochure that yields no text is a document the chatbot silently cannot see,
    # so it has to be visible rather than merely absent.
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        String(16), nullable=False, default=ExtractionStatus.PENDING,
        server_default=ExtractionStatus.PENDING.value, index=True,
    )
    extraction_error: Mapped[str | None] = mapped_column(Text)

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_document_deal_kind", "deal_id", "kind"),
        __import__("sqlalchemy").CheckConstraint(
            "deal_id IS NOT NULL OR company_id IS NOT NULL",
            name="document_needs_an_owner",
        ),
    )


class ActivityLog(Base, TimestampMixin):
    """One row per change, on every entity.

    Kept in a schema this small for two reasons: "who changed this price" gets asked eventually,
    and the "which deals have gone quiet" screen is a query over this table.
    """

    __tablename__ = "activity_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    # Denormalised so a deal's whole history is one indexed scan.
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("deal.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("company.id", ondelete="CASCADE"), index=True
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    actor_label: Mapped[str | None] = mapped_column(String(160))
    action: Mapped[ActivityAction] = mapped_column(String(20), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONVariant)
    after: Mapped[dict | None] = mapped_column(JSONVariant)

    __table_args__ = (
        Index("ix_activity_entity", "entity_type", "entity_id"),
        Index("ix_activity_deal_created", "deal_id", "created_at"),
    )
