"""Companies — everyone Ecolink deals with, on either side."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.deps import current_user
from app.db import get_db
from app.enums import ActivityAction, CompanyStatus, DocumentKind, ReferenceDomain as D
from app.models import (
    ActivityLog,
    Company,
    CompanyCertification,
    CompanyClient,
    CompanyProcess,
    CompanyProduct,
    Contact,
    Deal,
    DealParty,
    Document,
    ReferenceItem,
    User,
)
from app.schemas import (
    CompanyDetail,
    CompanyIn,
    CompanyRow,
    ContactIn,
    ContactOut,
    Msg,
    ProcessIn,
    TagIn,
)
from app.seed.taxonomy import resolve

router = APIRouter(prefix="/companies", tags=["companies"])


def _ref_or_400(db: Session, domain: D, text: str, label: str) -> ReferenceItem:
    item = resolve(db, domain, text)
    if item is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"'{text}' is not a known {label}. Pick from the list or add it in master data.",
        )
    return item


def _names(db: Session, company_id: uuid.UUID) -> tuple[list[str], list[str], list[str]]:
    def load(link, fk):
        return list(db.scalars(
            select(ReferenceItem.name).join(link, fk == ReferenceItem.id)
            .where(link.company_id == company_id).order_by(ReferenceItem.name)
        ).all())

    return (
        load(CompanyProcess, CompanyProcess.process_id),
        load(CompanyProduct, CompanyProduct.product_id),
        load(CompanyCertification, CompanyCertification.certification_id),
    )


def _row(db: Session, company: Company) -> CompanyRow:
    """Built field by field rather than by model_validate.

    Company has relationships called `processes`, `products` and `certifications` holding ORM
    objects, and the response model has fields of the same names holding strings. Letting
    pydantic read attributes off the instance picks up the relationships and fails to coerce
    them.
    """
    processes, products, certs = _names(db, company.id)
    has_brochure = db.scalar(
        select(func.count(Document.id)).where(
            Document.company_id == company.id, Document.kind == DocumentKind.BROCHURE
        )
    ) or 0
    return CompanyRow(
        id=company.id, name=company.name, city=company.city, country_id=company.country_id,
        buys=company.buys, sells=company.sells, status=company.status,
        processes=processes, products=products, certifications=certs,
        has_brochure=bool(has_brochure),
    )


@router.get("", response_model=list[CompanyRow])
def list_companies(
    search: str | None = Query(None, max_length=160),
    process: str | None = None,
    product: str | None = None,
    certification: str | None = None,
    country: str | None = None,
    buys: bool | None = None,
    sells: bool | None = None,
    company_status: CompanyStatus | None = None,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[CompanyRow]:
    """Filtered list. Each facet is an EXISTS so two filters must hold for the same company."""
    stmt = select(Company)

    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(Company.name).like(pattern),
                              func.lower(Company.legal_name).like(pattern),
                              func.lower(Company.city).like(pattern)))
    if buys is not None:
        stmt = stmt.where(Company.buys.is_(buys))
    if sells is not None:
        stmt = stmt.where(Company.sells.is_(sells))
    if company_status:
        stmt = stmt.where(Company.status == company_status)
    if country:
        item = resolve(db, D.COUNTRY, country)
        if item:
            stmt = stmt.where(Company.country_id == item.id)

    for value, domain, link, fk in [
        (process, D.PROCESS, CompanyProcess, CompanyProcess.process_id),
        (product, D.PRODUCT, CompanyProduct, CompanyProduct.product_id),
        (certification, D.CERTIFICATION, CompanyCertification,
         CompanyCertification.certification_id),
    ]:
        if not value:
            continue
        item = resolve(db, domain, value)
        if item is None:
            return []      # an unknown filter value matches nothing, rather than everything
        stmt = stmt.where(
            select(link.id).where(link.company_id == Company.id, fk == item.id).exists()
        )

    rows = db.scalars(stmt.order_by(Company.name)).all()
    return [_row(db, c) for c in rows]


@router.post("", response_model=CompanyDetail, status_code=201)
def create_company(
    body: CompanyIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CompanyDetail:
    payload = body.model_dump(exclude={"country_code"})
    company = Company(**payload)
    if body.country_code:
        company.country_id = _ref_or_400(db, D.COUNTRY, body.country_code, "country").id

    db.add(company)
    try:
        db.flush()
    except Exception:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"{body.name} already exists in {body.city or 'that city'}")

    db.add(ActivityLog(entity_type="Company", entity_id=company.id, company_id=company.id,
                       actor_user_id=user.id, actor_label=user.name,
                       action=ActivityAction.CREATE, summary=f"Added {company.name}"))
    db.commit()
    db.refresh(company)
    return _detail(db, company)


def _detail(db: Session, company: Company) -> CompanyDetail:
    row = _row(db, company).model_dump()
    open_deals = db.scalar(
        select(func.count(func.distinct(DealParty.deal_id)))
        .join(Deal, Deal.id == DealParty.deal_id)
        .where(DealParty.company_id == company.id,
               Deal.status.notin_(["COMPLETED", "LOST"]))
    ) or 0
    clients = list(db.scalars(
        select(CompanyClient.client_name).where(CompanyClient.company_id == company.id)
        .order_by(CompanyClient.is_current.desc(), CompanyClient.client_name)
    ).all())
    contacts = db.scalars(
        select(Contact).where(Contact.company_id == company.id)
        .order_by(Contact.is_primary.desc(), Contact.name)
    ).all()

    return CompanyDetail(
        **row,
        legal_name=company.legal_name, address=company.address, website=company.website,
        tax_id=company.tax_id, payment_terms=company.payment_terms,
        quality_requirements=company.quality_requirements,
        capacity_notes=company.capacity_notes, machinery_notes=company.machinery_notes,
        moq_notes=company.moq_notes, lead_time_notes=company.lead_time_notes,
        notes=company.notes,
        contacts=[ContactOut.model_validate(c) for c in contacts],
        clients=clients, open_deals=open_deals,
    )


def _get(db: Session, company_id: uuid.UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return company


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: uuid.UUID, _: User = Depends(current_user),
                db: Session = Depends(get_db)) -> CompanyDetail:
    return _detail(db, _get(db, company_id))


@router.patch("/{company_id}", response_model=CompanyDetail)
def update_company(company_id: uuid.UUID, body: CompanyIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> CompanyDetail:
    company = _get(db, company_id)
    payload = body.model_dump(exclude_unset=True, exclude={"country_code"})
    for field, value in payload.items():
        setattr(company, field, value)
    if body.country_code:
        company.country_id = _ref_or_400(db, D.COUNTRY, body.country_code, "country").id

    db.add(ActivityLog(entity_type="Company", entity_id=company.id, company_id=company.id,
                       actor_user_id=user.id, actor_label=user.name,
                       action=ActivityAction.UPDATE, summary=f"Updated {company.name}"))
    db.commit()
    db.refresh(company)
    return _detail(db, company)


@router.post("/{company_id}/contacts", response_model=ContactOut, status_code=201)
def add_contact(company_id: uuid.UUID, body: ContactIn, _: User = Depends(current_user),
                db: Session = Depends(get_db)) -> ContactOut:
    _get(db, company_id)
    if body.is_primary:
        for existing in db.scalars(
            select(Contact).where(Contact.company_id == company_id, Contact.is_primary.is_(True))
        ).all():
            existing.is_primary = False

    contact = Contact(company_id=company_id, **body.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return ContactOut.model_validate(contact)


@router.put("/{company_id}/processes", response_model=CompanyDetail)
def upsert_process(company_id: uuid.UUID, body: ProcessIn, _: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> CompanyDetail:
    company = _get(db, company_id)
    item = _ref_or_400(db, D.PROCESS, body.process_code, "process")

    row = db.scalars(
        select(CompanyProcess).where(CompanyProcess.company_id == company_id,
                                     CompanyProcess.process_id == item.id)
    ).first() or CompanyProcess(company_id=company_id, process_id=item.id)
    for field, value in body.model_dump(exclude={"process_code"}).items():
        setattr(row, field, value)
    db.add(row)
    db.commit()
    return _detail(db, company)


@router.post("/{company_id}/products", response_model=CompanyDetail, status_code=201)
def add_product(company_id: uuid.UUID, body: TagIn, _: User = Depends(current_user),
                db: Session = Depends(get_db)) -> CompanyDetail:
    company = _get(db, company_id)
    item = _ref_or_400(db, D.PRODUCT, body.code or body.name or "", "product")
    if not db.scalars(select(CompanyProduct).where(
        CompanyProduct.company_id == company_id, CompanyProduct.product_id == item.id
    )).first():
        db.add(CompanyProduct(company_id=company_id, product_id=item.id))
        db.commit()
    return _detail(db, company)


@router.post("/{company_id}/certifications", response_model=CompanyDetail, status_code=201)
def add_certification(company_id: uuid.UUID, body: TagIn, _: User = Depends(current_user),
                      db: Session = Depends(get_db)) -> CompanyDetail:
    company = _get(db, company_id)
    item = _ref_or_400(db, D.CERTIFICATION, body.code or body.name or "", "certification")
    if not db.scalars(select(CompanyCertification).where(
        CompanyCertification.company_id == company_id,
        CompanyCertification.certification_id == item.id
    )).first():
        db.add(CompanyCertification(company_id=company_id, certification_id=item.id))
        db.commit()
    return _detail(db, company)


@router.post("/{company_id}/clients", response_model=CompanyDetail, status_code=201)
def add_client(company_id: uuid.UUID, body: TagIn, _: User = Depends(current_user),
               db: Session = Depends(get_db)) -> CompanyDetail:
    """Brands this factory works for. Free text — these are Zara and Uniqlo, not our records."""
    company = _get(db, company_id)
    name = (body.name or body.code or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="A client name is required")
    if not db.scalars(select(CompanyClient).where(
        CompanyClient.company_id == company_id, CompanyClient.client_name == name
    )).first():
        db.add(CompanyClient(company_id=company_id, client_name=name))
        db.commit()
    return _detail(db, company)


@router.delete("/{company_id}", response_model=Msg)
def delete_company(company_id: uuid.UUID, _: User = Depends(current_user),
                   db: Session = Depends(get_db)) -> Msg:
    company = _get(db, company_id)
    if db.scalar(select(func.count(DealParty.id)).where(DealParty.company_id == company_id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This company is on a deal. Mark it inactive instead of deleting it.",
        )
    db.delete(company)
    db.commit()
    return Msg(detail="Deleted")
