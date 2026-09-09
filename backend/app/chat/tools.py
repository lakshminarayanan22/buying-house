"""What the branches can actually do.

Plain functions, callable from a test or an endpoint without a model in the loop. Phase 1 of
the plan is exactly this file — the queries validated before anything generates them.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.enums import ReferenceDomain as D
from app.models import (
    Company,
    CompanyCertification,
    CompanyProcess,
    CompanyProduct,
    Deal,
    DealParty,
    ReferenceItem,
)
from app.seed.taxonomy import resolve

logger = logging.getLogger(__name__)

_ro_sessionmaker = None


def readonly_session() -> Session:
    """A session on the SELECT-only role.

    Not an application convention — an actual Postgres role that cannot write. If a generated
    statement slips past the guard, the database still refuses it.
    """
    global _ro_sessionmaker
    if _ro_sessionmaker is None:
        url = settings.database_url_readonly or settings.database_url
        if url == settings.database_url:
            logger.warning(
                "DATABASE_URL_READONLY is not set — read queries will run on the read/write "
                "role. The guard still applies, but the database-level backstop does not."
            )
        _ro_sessionmaker = sessionmaker(
            bind=create_engine(url, pool_pre_ping=True), expire_on_commit=False
        )
    return _ro_sessionmaker()


# --------------------------------------------------------------------- find_company
@dataclass
class CompanyMatch:
    company_id: str
    name: str
    city: str | None
    buys: bool
    sells: bool
    processes: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    moq_notes: str | None = None
    capacity_notes: str | None = None
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id, "name": self.name, "city": self.city,
            "buys": self.buys, "sells": self.sells, "processes": self.processes,
            "products": self.products, "certifications": self.certifications,
            "moq_notes": self.moq_notes, "capacity_notes": self.capacity_notes,
            "reasons": self.reasons, "gaps": self.gaps,
        }


def find_company(
    db: Session,
    *,
    process: str | None = None,
    product: str | None = None,
    certification: str | None = None,
    country: str | None = None,
    city: str | None = None,
    buys: bool | None = None,
    sells: bool | None = None,
    free_text: str | None = None,
    limit: int = 3,
) -> list[CompanyMatch]:
    """Structured filter first; semantic search only when structure cannot express the question.

    With ten companies of taxonomy-backed data, "who can dye and holds GOTS" is a WHERE clause.
    Similarity search would be slower, non-deterministic, and unable to express "MOQ under
    500 kg" at all. The brochure text is the fallback for what the taxonomy has no word for —
    "who does cooling finishes" — not the primary path.
    """
    stmt = select(Company)
    reasons_for_all: list[str] = []

    for value, domain, link, fk, label in [
        (process, D.PROCESS, CompanyProcess, CompanyProcess.process_id, "process"),
        (product, D.PRODUCT, CompanyProduct, CompanyProduct.product_id, "product"),
        (certification, D.CERTIFICATION, CompanyCertification,
         CompanyCertification.certification_id, "certification"),
    ]:
        if not value:
            continue
        item = resolve(db, domain, value)
        if item is None:
            # An unknown filter value matches nothing rather than everything.
            return []
        stmt = stmt.where(
            select(link.id).where(link.company_id == Company.id, fk == item.id).exists())
        reasons_for_all.append(f"{label}: {item.name}")

    if country:
        item = resolve(db, D.COUNTRY, country)
        if item is None:
            return []
        stmt = stmt.where(Company.country_id == item.id)
        reasons_for_all.append(f"country: {item.name}")
    if city:
        stmt = stmt.where(func.lower(Company.city) == city.lower())
        reasons_for_all.append(f"city: {city}")
    if buys is not None:
        stmt = stmt.where(Company.buys.is_(buys))
    if sells is not None:
        stmt = stmt.where(Company.sells.is_(sells))

    structured = bool(reasons_for_all or buys is not None or sells is not None)
    rows = db.scalars(stmt.order_by(Company.name)).all() if structured else []

    if not rows and free_text:
        rows = _semantic_companies(db, free_text)
        reasons_for_all = [f"matched brochure text for “{free_text}”"]
    elif not structured and free_text:
        rows = _semantic_companies(db, free_text)
        reasons_for_all = [f"matched brochure text for “{free_text}”"]

    return [_describe(db, c, reasons_for_all) for c in rows[:limit]]


def _semantic_companies(db: Session, query: str) -> list[Company]:
    """Companies whose documents match, in retrieval order, de-duplicated."""
    from app.retrieval import search

    seen: list[uuid.UUID] = []
    for hit in search(db, query, top_k=12):
        if hit.company_id and hit.company_id not in seen:
            seen.append(hit.company_id)
    return [db.get(Company, cid) for cid in seen if db.get(Company, cid) is not None]


def _describe(db: Session, company: Company, reasons: list[str]) -> CompanyMatch:
    def names(link, fk):
        return list(db.scalars(
            select(ReferenceItem.name).join(link, fk == ReferenceItem.id)
            .where(link.company_id == company.id).order_by(ReferenceItem.name)).all())

    processes = names(CompanyProcess, CompanyProcess.process_id)
    products = names(CompanyProduct, CompanyProduct.product_id)
    certs = names(CompanyCertification, CompanyCertification.certification_id)

    # What we do *not* know is as useful as what we do. "No capacity figure on file" stops
    # someone quoting a customer on a number that was never recorded.
    gaps = [label for label, missing in [
        ("no capacity on file", not company.capacity_notes),
        ("no minimum order on file", not company.moq_notes),
        ("no certifications recorded", not certs),
        ("no brochure uploaded", not db.scalar(
            select(func.count()).select_from(text("document"))
            .where(text("company_id = :cid AND kind = 'BROCHURE'")).params(cid=company.id))),
    ] if missing]

    return CompanyMatch(
        company_id=str(company.id), name=company.name, city=company.city,
        buys=company.buys, sells=company.sells,
        processes=processes, products=products, certifications=certs,
        moq_notes=company.moq_notes, capacity_notes=company.capacity_notes,
        reasons=list(reasons), gaps=gaps,
    )


# ------------------------------------------------------------------------ run_select
def run_select(sql: str) -> dict[str, Any]:
    """Execute a validated SELECT on the read-only role, capped and timed out."""
    from app.chat.guard import Kind, check

    checked = check(sql, allow_write=False)
    if checked.kind is not Kind.SELECT:
        raise RuntimeError("run_select received something that is not a SELECT")

    db = readonly_session()
    try:
        db.execute(text(f"SET LOCAL statement_timeout = {settings.sql_statement_timeout_ms}"))
        result = db.execute(text(checked.sql))
        columns = list(result.keys())
        rows = result.fetchmany(settings.sql_row_cap + 1)
        truncated = len(rows) > settings.sql_row_cap
        rows = rows[: settings.sql_row_cap]
        return {
            "sql": checked.sql,
            "columns": columns,
            "rows": [dict(zip(columns, (_clean(v) for v in row))) for row in rows],
            "truncated": truncated,
        }
    finally:
        db.rollback()
        db.close()


def _clean(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
