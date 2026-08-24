"""Declarative base, shared mixins, and the taxonomy foreign-key helper."""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    MetaData,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.enums import ReferenceDomain

# Predictable constraint names keep Alembic diffs and Postgres errors readable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# JSONB on Postgres, plain JSON on SQLite (test suite).
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


def uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key, generated app-side with uuid4."""
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


# --------------------------------------------------------------------- taxonomy FKs
#
# Every taxonomy value lives in one table (`reference_item`) namespaced by `domain`. A plain
# FK to reference_item.id would let a FIBRE row be stored in a process_type column and the
# database would happily accept it. §3 calls the taxonomy layer "the single most expensive
# mistake in the project", so the domain is enforced in Postgres, not in application code:
#
#   * reference_item carries UNIQUE (id, domain)
#   * the referencing table carries <name>_id AND <name>_domain
#   * a composite FK points at (id, domain), and a CHECK pins <name>_domain to one literal
#
# Cost is one narrow column per FK. Benefit is that a mis-domained reference is rejected by
# the database on insert, in every code path, forever.


def reference_id_col(*, nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), nullable=nullable, index=True)


def reference_domain_col(domain: ReferenceDomain, *, nullable: bool = False) -> Mapped[str]:
    return mapped_column(
        String(40),
        nullable=nullable,
        default=domain.value,
        server_default=domain.value,
    )


def reference_fk(table: str, name: str, domain: ReferenceDomain) -> tuple:
    """__table_args__ entries binding `<name>_id`/`<name>_domain` to one taxonomy domain.

    Usage:
        __table_args__ = (*reference_fk("supplier_process", "process_type",
                                        ReferenceDomain.PROCESS_TYPE),)
    """
    id_col, domain_col = f"{name}_id", f"{name}_domain"
    return (
        ForeignKeyConstraint(
            [id_col, domain_col],
            ["reference_item.id", "reference_item.domain"],
            name=f"fk_{table}_{name}_reference_item",
            ondelete="RESTRICT",
        ),
        # Named without repeating the table: the naming convention already prefixes
        # "ck_<table>_", and Postgres truncates identifiers at 63 characters — a name that
        # gets truncated no longer matches the metadata, and `alembic check` then reports
        # drift on every run forever.
        CheckConstraint(
            f"{domain_col} = '{domain.value}'",
            name=f"{name}_domain",
        ),
    )
