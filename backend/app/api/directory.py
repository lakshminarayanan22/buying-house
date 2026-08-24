"""The supplier directory (§12 step 5) — the first screen that actually feels useful.

This is also the honest prototype of §10 step 2. Every facet here is a deterministic hard
filter over structured data: process, category, fibre, GSM, MOQ, certification validity,
month-wise free capacity, geography. When the agent is built, it runs these same predicates
before it scores anything — so if the directory returns nothing useful today, no amount of
model quality will fix it later.
"""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, and_, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import get_principal
from app.db import get_db
from app.enums import CapacityUom, OrgStatus, OrgType, SupplierTier, VerificationStatus
from app.models import (
    Organization,
    ReferenceItem,
    SupplierCapability,
    SupplierCapabilityFibre,
    SupplierCapacityCalendar,
    SupplierCertification,
    SupplierProcess,
    SupplierProfile,
)
from app.rbac import Action, Principal, can
from app.rbac.policy import redact_identity
from app.schemas.common import Page
from app.services.taxonomy import resolve

router = APIRouter(prefix="/directory", tags=["directory"])


def _codes_to_ids(db: Session, domain, codes: list[str]) -> list[uuid.UUID]:
    """Resolve filter codes to ids, silently dropping unknown ones.

    A filter is not a form: an unrecognised facet value should narrow nothing rather than
    return a 400 in the middle of someone refining a search.
    """
    ids = []
    for code in codes:
        item = resolve(db, domain, code)
        if item is not None:
            ids.append(item.id)
    return ids


def _category_subtree_ids(db: Session, category_id: uuid.UUID) -> list[uuid.UUID]:
    """A category filter must match its children too.

    Someone filtering on "Knitwear" wants the T-shirt and polo suppliers. One prefix scan on
    the materialised path, which is what `path` exists for.
    """
    root = db.get(ReferenceItem, category_id)
    if root is None:
        return [category_id]
    rows = db.scalars(
        select(ReferenceItem.id).where(
            or_(ReferenceItem.id == root.id, ReferenceItem.path.like(f"{root.path}/%"))
        )
    ).all()
    return list(rows)


def _apply_filters(
    stmt: Select,
    db: Session,
    *,
    process_codes: list[str],
    category_codes: list[str],
    fibre_codes: list[str],
    certification_codes: list[str],
    country_code: str | None,
    city: str | None,
    gsm: int | None,
    max_moq: float | None,
    moq_uom: CapacityUom | None,
    capacity_month: date | None,
    min_available_qty: float | None,
    tier: SupplierTier | None,
    min_completeness: int | None,
) -> Select:
    from app.enums import ReferenceDomain as D

    # Each facet is an EXISTS rather than a JOIN: a supplier with three processes must appear
    # once, and two facets must both hold for the same supplier without multiplying rows.
    if process_codes:
        ids = _codes_to_ids(db, D.PROCESS_TYPE, process_codes)
        if ids:
            stmt = stmt.where(
                select(SupplierProcess.id)
                .where(
                    SupplierProcess.org_id == Organization.id,
                    SupplierProcess.process_type_id.in_(ids),
                )
                .exists()
            )

    if category_codes:
        category_ids: list[uuid.UUID] = []
        for cid in _codes_to_ids(db, D.PRODUCT_CATEGORY, category_codes):
            category_ids.extend(_category_subtree_ids(db, cid))
        if category_ids:
            stmt = stmt.where(
                select(SupplierCapability.id)
                .where(
                    SupplierCapability.org_id == Organization.id,
                    SupplierCapability.product_category_id.in_(category_ids),
                )
                .exists()
            )

    if fibre_codes:
        ids = _codes_to_ids(db, D.FIBRE, fibre_codes)
        if ids:
            stmt = stmt.where(
                select(SupplierCapabilityFibre.id)
                .join(
                    SupplierCapability,
                    SupplierCapability.id == SupplierCapabilityFibre.capability_id,
                )
                .where(
                    SupplierCapability.org_id == Organization.id,
                    SupplierCapabilityFibre.fibre_id.in_(ids),
                )
                .exists()
            )

    if certification_codes:
        ids = _codes_to_ids(db, D.CERTIFICATION, certification_codes)
        if ids:
            today = date.today()
            # Held, verified, and unexpired. An expired certificate is not a certificate —
            # this is the predicate §10 step 2 runs, and it must not drift from it.
            stmt = stmt.where(
                select(SupplierCertification.id)
                .where(
                    SupplierCertification.org_id == Organization.id,
                    SupplierCertification.certification_id.in_(ids),
                    SupplierCertification.verification_status == VerificationStatus.VERIFIED,
                    or_(
                        SupplierCertification.valid_till.is_(None),
                        SupplierCertification.valid_till >= today,
                    ),
                )
                .exists()
            )

    if country_code:
        country = resolve(db, D.COUNTRY, country_code)
        if country is not None:
            stmt = stmt.where(Organization.country_id == country.id)

    if city:
        stmt = stmt.where(func.lower(Organization.city) == city.lower())

    if gsm is not None:
        # An open-ended band still matches: a supplier who gave only gsm_min should not vanish
        # from the results for being less precise than their neighbour.
        stmt = stmt.where(
            select(SupplierCapability.id)
            .where(
                SupplierCapability.org_id == Organization.id,
                or_(SupplierCapability.gsm_min.is_(None), SupplierCapability.gsm_min <= gsm),
                or_(SupplierCapability.gsm_max.is_(None), SupplierCapability.gsm_max >= gsm),
            )
            .exists()
        )

    if max_moq is not None:
        conditions = [
            SupplierProcess.org_id == Organization.id,
            SupplierProcess.min_order_qty <= max_moq,
        ]
        # Comparing a MOQ in kg against an order in pieces is meaningless; if the caller names
        # a unit, only rows in that unit are compared.
        if moq_uom is not None:
            conditions.append(SupplierProcess.moq_uom == moq_uom)
        stmt = stmt.where(select(SupplierProcess.id).where(and_(*conditions)).exists())

    if capacity_month is not None:
        month = capacity_month.replace(day=1)
        conditions = [
            SupplierCapacityCalendar.org_id == Organization.id,
            SupplierCapacityCalendar.month == month,
        ]
        if min_available_qty is not None:
            conditions.append(SupplierCapacityCalendar.available_qty >= min_available_qty)
        stmt = stmt.where(select(SupplierCapacityCalendar.id).where(and_(*conditions)).exists())

    if tier is not None or min_completeness is not None:
        conditions = [SupplierProfile.org_id == Organization.id]
        if tier is not None:
            conditions.append(SupplierProfile.completeness_tier == tier)
        if min_completeness is not None:
            conditions.append(SupplierProfile.completeness_pct >= min_completeness)
        stmt = stmt.where(select(SupplierProfile.org_id).where(and_(*conditions)).exists())

    return stmt


@router.get("/suppliers")
def search_suppliers(
    process: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    fibre: list[str] = Query(default=[]),
    certification: list[str] = Query(default=[]),
    country: str | None = None,
    city: str | None = None,
    gsm: int | None = Query(None, ge=0, le=2000),
    max_moq: float | None = Query(None, ge=0),
    moq_uom: CapacityUom | None = None,
    capacity_month: date | None = None,
    min_available_qty: float | None = Query(None, ge=0),
    tier: SupplierTier | None = None,
    min_completeness: int | None = Query(None, ge=0, le=100),
    include_unverified: bool = False,
    search: str | None = Query(None, max_length=160),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[dict]:
    """Faceted supplier search.

    Internal staff see identities. A brand sees the same capability data with the factory's
    name, address and contact details withheld until an explicit reveal — that gatekeeping is
    the buying house's commercial value (§2), so it is applied here in the serialiser, not left
    to the frontend to remember.
    """
    stmt = select(Organization).where(Organization.type == OrgType.SUPPLIER)

    # Unverified suppliers are our working drafts; only internal staff may ask to see them.
    if principal.is_internal and include_unverified:
        pass
    else:
        stmt = stmt.where(Organization.status == OrgStatus.VERIFIED)

    if not principal.is_internal:
        if principal.org_type != OrgType.BRAND:
            # A supplier browsing the supplier directory has no business case and every
            # competitive incentive.
            return Page[dict](items=[], total=0, page=page, page_size=page_size)

    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Organization.legal_name).like(pattern),
                func.lower(Organization.trade_name).like(pattern),
                func.lower(Organization.city).like(pattern),
            )
        )

    stmt = _apply_filters(
        stmt, db,
        process_codes=process, category_codes=category, fibre_codes=fibre,
        certification_codes=certification, country_code=country, city=city, gsm=gsm,
        max_moq=max_moq, moq_uom=moq_uom, capacity_month=capacity_month,
        min_available_qty=min_available_qty, tier=tier, min_completeness=min_completeness,
    )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Organization.legal_name).offset((page - 1) * page_size).limit(page_size)
    ).all()

    items: list[dict] = []
    for org in rows:
        profile = db.get(SupplierProfile, org.id)
        process_names = db.scalars(
            select(ReferenceItem.name)
            .join(SupplierProcess, SupplierProcess.process_type_id == ReferenceItem.id)
            .where(SupplierProcess.org_id == org.id)
            .order_by(ReferenceItem.name)
        ).all()
        category_names = db.scalars(
            select(ReferenceItem.name)
            .join(SupplierCapability, SupplierCapability.product_category_id == ReferenceItem.id)
            .where(SupplierCapability.org_id == org.id)
            .order_by(ReferenceItem.name)
        ).all()
        cert_names = db.scalars(
            select(distinct(ReferenceItem.name))
            .join(
                SupplierCertification,
                SupplierCertification.certification_id == ReferenceItem.id,
            )
            .where(
                SupplierCertification.org_id == org.id,
                SupplierCertification.verification_status == VerificationStatus.VERIFIED,
                or_(
                    SupplierCertification.valid_till.is_(None),
                    SupplierCertification.valid_till >= date.today(),
                ),
            )
        ).all()

        payload = {
            "id": str(org.id),
            "legal_name": org.legal_name,
            "trade_name": org.trade_name,
            "website": org.website,
            "city": org.city,
            "state": org.state,
            "status": org.status,
            "processes": list(process_names),
            "categories": list(category_names),
            "certifications": list(cert_names),
            "completeness_pct": profile.completeness_pct if profile else 0,
            "tier": profile.completeness_tier if profile else None,
            "is_identity_visible": can(principal, Action.VIEW_IDENTITY, org),
        }
        if not payload["is_identity_visible"]:
            # Give the row a stable, meaningless handle so a brand can still say "supplier B"
            # in a conversation with us without ever learning who it is.
            payload["masked_ref"] = f"SUP-{str(org.id)[:8].upper()}"
        items.append(redact_identity(principal, org, payload))

    return Page[dict](items=items, total=total, page=page, page_size=page_size)


@router.get("/facets")
def facet_counts(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict[str, list[dict]]:
    """Counts per facet value, so the filter panel can show what is actually there.

    Restricted to verified suppliers for everyone: a facet count is a data leak in miniature
    if it reveals how many unverified factories we are talking to.
    """
    verified = select(Organization.id).where(
        Organization.type == OrgType.SUPPLIER, Organization.status == OrgStatus.VERIFIED
    )

    def _counts(join_model, id_column) -> list[dict]:
        rows = db.execute(
            select(ReferenceItem.code, ReferenceItem.name, func.count(distinct(join_model.org_id)))
            .join(join_model, id_column == ReferenceItem.id)
            .where(join_model.org_id.in_(verified))
            .group_by(ReferenceItem.code, ReferenceItem.name)
            .order_by(func.count(distinct(join_model.org_id)).desc())
        ).all()
        return [{"code": c, "name": n, "count": count} for c, n, count in rows]

    return {
        "process": _counts(SupplierProcess, SupplierProcess.process_type_id),
        "category": _counts(SupplierCapability, SupplierCapability.product_category_id),
        "certification": _counts(SupplierCertification, SupplierCertification.certification_id),
    }
