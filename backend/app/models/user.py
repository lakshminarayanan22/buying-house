"""Users, credentials, and the OTP login path that suppliers actually use."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import Role, UserStatus
from app.models.base import Base, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.organization import Organization


class User(Base, TimestampMixin):
    """A person who logs in.

    org_id is NULL for internal staff and NOT NULL for brand/supplier users. That invariant is
    the backbone of the access-control layer, so the database enforces it rather than trusting
    every code path to remember.
    """

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(String(40), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(240), index=True)
    phone: Mapped[str | None] = mapped_column(String(30), index=True)
    whatsapp: Mapped[str | None] = mapped_column(String(30))

    # Argon2id. Null for supplier users who only ever log in by OTP — a factory owner will not
    # keep a password, and forcing one just produces "Factory@123" on a sticky note.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    language_pref: Mapped[str] = mapped_column(
        String(8), nullable=False, default="en", server_default="en"
    )
    status: Mapped[UserStatus] = mapped_column(
        String(20), nullable=False, default=UserStatus.INVITED,
        server_default=UserStatus.INVITED.value, index=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on password change / forced logout; session tokens carrying an older value are
    # rejected, which is how "disable this user right now" actually takes effect.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    organization: Mapped["Organization | None"] = relationship(
        back_populates="users", foreign_keys=[org_id]
    )

    __table_args__ = (
        # An org user must have an org; an internal user must not.
        CheckConstraint(
            "(role LIKE 'INTERNAL_%' AND org_id IS NULL) "
            "OR (role NOT LIKE 'INTERNAL_%' AND org_id IS NOT NULL)",
            name="app_user_org_matches_role",
        ),
        # Every user needs at least one way to be reached and identified.
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL", name="app_user_email_or_phone"
        ),
        UniqueConstraint("email", name="uq_app_user_email"),
        UniqueConstraint("phone", name="uq_app_user_phone"),
        Index("ix_app_user_org_role", "org_id", "role"),
    )

    @property
    def is_internal(self) -> bool:
        return Role(self.role).is_internal

    @property
    def side(self) -> str:
        return Role(self.role).side.value


class OtpChallenge(Base, TimestampMixin):
    """A pending phone/email one-time code.

    Only the hash of the code is stored. `attempts` is checked before comparison so a six-digit
    code cannot be brute-forced, and `consumed_at` makes it single-use.
    """

    __tablename__ = "otp_challenge"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    destination: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrandSupplierReveal(Base, TimestampMixin):
    """An explicit, logged decision to expose one side's identity to the other.

    §2 calls this gatekeeping the buying house's commercial value, and §11 lists identity
    leakage as a project killer. Modelling the reveal as a row — rather than a boolean buried
    in a workflow — means "who knows whom" is queryable, auditable, and revocable, and the
    access-control layer has exactly one place to look.
    """

    __tablename__ = "brand_supplier_reveal"

    id: Mapped[uuid.UUID] = uuid_pk()
    brand_org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    supplier_org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Which direction the identity flows. Both rows can exist; neither implies the other.
    brand_sees_supplier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    supplier_sees_brand: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    reason: Mapped[str | None] = mapped_column(String(500))
    revealed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("brand_org_id", "supplier_org_id", name="uq_reveal_brand_supplier"),
    )
