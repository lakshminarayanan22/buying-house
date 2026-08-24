"""Organizations — the tenant boundary. Every tenant-scoped table carries org_id."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

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

from app.enums import OrgStatus, OrgType
from app.models.base import Base, JSONVariant, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class Organization(Base, TimestampMixin):
    """A brand or a supplier. Internal staff have no organization (users.org_id is NULL).

    §2: brands and suppliers never see each other's identity until an explicit reveal. That
    rule is enforced in rbac/, but it starts here — an org row is the unit of isolation.
    """

    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[OrgType] = mapped_column(String(16), nullable=False, index=True)

    legal_name: Mapped[str] = mapped_column(String(240), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(240), index=True)

    country_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("reference_item.id", ondelete="RESTRICT"), index=True
    )
    state: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    pincode: Mapped[str | None] = mapped_column(String(20))

    gst_no: Mapped[str | None] = mapped_column(String(30))
    pan: Mapped[str | None] = mapped_column(String(20))
    iec_code: Mapped[str | None] = mapped_column(String(30))
    website: Mapped[str | None] = mapped_column(String(240))
    year_established: Mapped[int | None] = mapped_column(Integer)
    employee_count: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[OrgStatus] = mapped_column(
        String(20), nullable=False, default=OrgStatus.DRAFT, server_default=OrgStatus.DRAFT.value,
        index=True,
    )
    verification_notes: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    # §5.2: realistically ~70% of year-one suppliers are keyed in by our own team. Flagging it
    # matters because a profile the supplier never saw is a weaker signal than one they filled.
    created_by_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    # Set when the row came from an Excel bulk import, so a bad import can be traced or undone.
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)

    users: Mapped[list["User"]] = relationship(
        back_populates="organization", foreign_keys="User.org_id"
    )
    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_organization_type_status", "type", "status"),
        # GST is the closest thing to a national unique key for an Indian entity; letting the
        # same factory be onboarded twice is what makes a supplier directory untrustworthy.
        UniqueConstraint("gst_no", name="uq_organization_gst_no"),
    )

    @property
    def display_name(self) -> str:
        return self.trade_name or self.legal_name

    @property
    def is_verified(self) -> bool:
        return self.status == OrgStatus.VERIFIED


class Contact(Base, TimestampMixin):
    """Key people at an org, including those who never get a login.

    Most factory owners will not become users; their phone number still has to live somewhere
    the merchandiser can find it.
    """

    __tablename__ = "contact"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(240))
    phone: Mapped[str | None] = mapped_column(String(30))
    whatsapp: Mapped[str | None] = mapped_column(String(30))
    language_pref: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    organization: Mapped[Organization] = relationship(back_populates="contacts")


class OrgInvite(Base, TimestampMixin):
    """A token-based, expiring invitation to a brand or supplier (§5.1 step 1).

    The token itself is a JWT; only its hash is stored so a database leak cannot be replayed
    as a login. `accepted_at` makes it single-use.
    """

    __tablename__ = "org_invite"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str | None] = mapped_column(String(240))
    phone: Mapped[str | None] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ImportBatch(Base, TimestampMixin):
    """One Excel bulk-import run (§5.2), kept so a bad sheet can be audited row by row."""

    __tablename__ = "import_batch"

    id: Mapped[uuid.UUID] = uuid_pk()
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    imported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Per-row outcome: [{"row": 4, "status": "error", "message": "unknown process 'kniting'"}]
    row_results: Mapped[list | None] = mapped_column(JSONVariant)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
