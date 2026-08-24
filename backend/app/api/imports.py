"""Excel bulk import (§5.2) — how your existing supplier list gets in on day one.

Two properties matter more than features here. It is **idempotent**: re-importing a corrected
sheet updates the same factories instead of creating duplicates, keyed on GST and then on
(name, city). And it is **row-independent**: one bad row is reported with its row number and
reason, and the other 199 still land.

Free-text columns resolve through the alias table, so "S/J", "process house" and "kgs" all
land on the right taxonomy value rather than in a review queue.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_internal
from app.db import get_db
from app.enums import (
    ActivityAction,
    CapacityUom,
    DataSource,
    OrgStatus,
    OrgType,
    ReferenceDomain,
)
from app.models import (
    Contact,
    ImportBatch,
    Organization,
    SupplierCapability,
    SupplierProcess,
    SupplierProfile,
)
from app.rbac import Action, Principal, require
from app.services import activity, completeness
from app.services.taxonomy import resolve, resolve_or_queue

router = APIRouter(prefix="/imports", tags=["imports"])

# (column, required, help text shown in the template's second row)
TEMPLATE_COLUMNS = [
    ("factory_name", True, "Legal or trade name of the unit"),
    ("city", True, "e.g. Tiruppur"),
    ("country", False, "Defaults to India. Name or ISO code"),
    ("state", False, ""),
    ("gst_no", False, "Used to avoid duplicates. Strongly recommended"),
    ("pan", False, ""),
    ("contact_name", True, ""),
    ("phone", True, "With country code, e.g. +91 90000 00000"),
    ("whatsapp", False, "Leave blank to use the phone number"),
    ("email", False, ""),
    ("processes", True, "Comma separated. e.g. Knitting - circular, Fabric dyeing"),
    ("categories", True, "Comma separated. e.g. T-shirts, Polo shirts"),
    ("fibres", False, "Comma separated. e.g. Cotton, Organic cotton"),
    ("monthly_capacity", False, "Number only"),
    ("capacity_uom", False, "PCS / KG / MTR / YRD / DOZ"),
    ("min_order_qty", False, "Number only"),
    ("moq_uom", False, "PCS / KG / MTR / YRD / DOZ"),
    ("lead_time_days", False, "Standard production lead time"),
    ("notes", False, ""),
]


@router.get("/suppliers/template")
def download_template(_: Principal = Depends(require_internal)) -> StreamingResponse:
    """An .xlsx with the expected headers, a help row, and one worked example."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Suppliers"

    header_fill = PatternFill("solid", fgColor="1F3A5F")
    for col, (name, required, _help) in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=name + (" *" if required else ""))
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = max(16, len(name) + 6)

    for col, (_name, _required, help_text) in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = ws.cell(row=2, column=col, value=help_text)
        cell.font = Font(italic=True, size=9, color="666666")

    example = {
        "factory_name": "Kovai Knits Pvt Ltd", "city": "Tiruppur", "country": "India",
        "state": "Tamil Nadu", "gst_no": "33AABCK1234M1Z5", "contact_name": "R. Murugan",
        "phone": "+91 90000 00000", "processes": "Knitting - circular, Stitching",
        "categories": "T-shirts, Polo shirts", "fibres": "Cotton, Organic cotton",
        "monthly_capacity": 250000, "capacity_uom": "PCS", "min_order_qty": 1000,
        "moq_uom": "PCS", "lead_time_days": 45,
    }
    for col, (name, _r, _h) in enumerate(TEMPLATE_COLUMNS, start=1):
        ws.cell(row=3, column=col, value=example.get(name, ""))

    ws.freeze_panes = "A4"

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="supplier-import-template.xlsx"'},
    )


def _split(value) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _number(value) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _uom(value) -> CapacityUom | None:
    if not value:
        return None
    try:
        return CapacityUom(str(value).strip().upper())
    except ValueError:
        return None


@router.post("/suppliers")
async def import_suppliers(
    file: UploadFile = File(...),
    dry_run: bool = False,
    principal: Principal = Depends(require_internal),
    db: Session = Depends(get_db),
) -> dict:
    """Import or update suppliers from the template.

    `dry_run=true` validates and reports without writing — worth doing on a 200-row sheet
    before committing to it.
    """
    require(principal, Action.BULK_IMPORT, "Organization")

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Upload an .xlsx file")

    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(await file.read()), data_only=True)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Could not read that workbook")

    ws = wb.active
    header_row = [str(c.value).strip().rstrip("*").strip() if c.value else "" for c in ws[1]]
    index = {name: i for i, name in enumerate(header_row) if name}

    missing = [name for name, required, _ in TEMPLATE_COLUMNS if required and name not in index]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required columns: {', '.join(missing)}",
        )

    batch = ImportBatch(filename=file.filename, imported_by_user_id=principal.user_id)
    db.add(batch)
    db.flush()

    results: list[dict] = []
    created = updated = errors = 0

    for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        def cell(name: str):
            position = index.get(name)
            return row[position] if position is not None and position < len(row) else None

        factory_name = (str(cell("factory_name")).strip() if cell("factory_name") else "")
        # Row 2 of the template is the help text and row 3 the example; skip both, and any
        # blank spacer rows a user leaves behind.
        if not factory_name or factory_name.lower() in {"none", "legal or trade name of the unit"}:
            continue

        # One SAVEPOINT per row. Without it the first bad row would roll back the batch
        # record and every supplier imported before it.
        savepoint = db.begin_nested()
        try:
            city = str(cell("city")).strip() if cell("city") else ""
            if not city:
                raise ValueError("city is required")

            contact_name = str(cell("contact_name")).strip() if cell("contact_name") else ""
            phone = str(cell("phone")).strip() if cell("phone") else ""
            if not contact_name or not phone:
                raise ValueError("contact_name and phone are required")

            process_names = _split(cell("processes"))
            category_names = _split(cell("categories"))
            if not process_names or not category_names:
                raise ValueError("at least one process and one category are required")

            gst = str(cell("gst_no")).strip() if cell("gst_no") else None

            # Idempotency: GST first, then name+city. Re-importing a corrected sheet must
            # update the same factories, not double the directory.
            org = None
            if gst:
                org = db.scalars(select(Organization).where(Organization.gst_no == gst)).first()
            if org is None:
                org = db.scalars(
                    select(Organization).where(
                        Organization.type == OrgType.SUPPLIER,
                        func.lower(Organization.legal_name) == factory_name.lower(),
                        func.lower(Organization.city) == city.lower(),
                    )
                ).first()

            is_new = org is None
            if is_new:
                org = Organization(
                    type=OrgType.SUPPLIER, legal_name=factory_name, trade_name=factory_name,
                    status=OrgStatus.DRAFT, created_by_internal=True,
                    created_by_user_id=principal.user_id, import_batch_id=batch.id,
                )
                db.add(org)
                db.flush()
                db.add(SupplierProfile(org_id=org.id, source=DataSource.INTERNAL_VERIFIED))

            org.city = city
            if cell("state"):
                org.state = str(cell("state")).strip()
            if gst:
                org.gst_no = gst
            if cell("pan"):
                org.pan = str(cell("pan")).strip()

            country = resolve(
                db, ReferenceDomain.COUNTRY,
                str(cell("country")).strip() if cell("country") else "IN",
            )
            if country is not None:
                org.country_id = country.id

            phone_value = phone
            whatsapp = str(cell("whatsapp")).strip() if cell("whatsapp") else phone_value
            existing_contact = db.scalars(
                select(Contact).where(Contact.org_id == org.id, Contact.is_primary.is_(True))
            ).first()
            if existing_contact is None:
                db.add(
                    Contact(
                        org_id=org.id, name=contact_name, phone=phone_value, whatsapp=whatsapp,
                        email=str(cell("email")).strip() if cell("email") else None,
                        is_primary=True,
                    )
                )
            else:
                existing_contact.name = contact_name
                existing_contact.phone = phone_value
                existing_contact.whatsapp = whatsapp

            capacity = _number(cell("monthly_capacity"))
            capacity_uom = _uom(cell("capacity_uom"))
            moq = _number(cell("min_order_qty"))
            moq_uom = _uom(cell("moq_uom"))
            lead_time = _number(cell("lead_time_days"))

            # The database rejects a quantity without its unit; catch it here so the row
            # reports a readable reason instead of aborting the whole import.
            if capacity is not None and capacity_uom is None:
                raise ValueError("capacity_uom is required when monthly_capacity is given")
            if moq is not None and moq_uom is None:
                raise ValueError("moq_uom is required when min_order_qty is given")

            unresolved: list[str] = []

            for name in process_names:
                item = resolve_or_queue(
                    db, ReferenceDomain.PROCESS_TYPE, name,
                    source_entity_type="ImportBatch", source_entity_id=batch.id,
                )
                if item is None:
                    unresolved.append(f"process '{name}'")
                    continue
                existing = db.scalars(
                    select(SupplierProcess).where(
                        SupplierProcess.org_id == org.id,
                        SupplierProcess.process_type_id == item.id,
                    )
                ).first()
                if existing is None:
                    existing = SupplierProcess(org_id=org.id, process_type_id=item.id)
                    db.add(existing)
                existing.monthly_capacity_value = capacity
                existing.capacity_uom = capacity_uom
                existing.min_order_qty = moq
                existing.moq_uom = moq_uom
                existing.standard_lead_time_days = int(lead_time) if lead_time else None
                existing.source = DataSource.INTERNAL_VERIFIED

            fibre_items = []
            for name in _split(cell("fibres")):
                item = resolve_or_queue(
                    db, ReferenceDomain.FIBRE, name,
                    source_entity_type="ImportBatch", source_entity_id=batch.id,
                )
                if item is None:
                    unresolved.append(f"fibre '{name}'")
                else:
                    fibre_items.append(item)

            for name in category_names:
                item = resolve_or_queue(
                    db, ReferenceDomain.PRODUCT_CATEGORY, name,
                    source_entity_type="ImportBatch", source_entity_id=batch.id,
                )
                if item is None:
                    unresolved.append(f"category '{name}'")
                    continue
                capability = db.scalars(
                    select(SupplierCapability).where(
                        SupplierCapability.org_id == org.id,
                        SupplierCapability.product_category_id == item.id,
                    )
                ).first()
                if capability is None:
                    capability = SupplierCapability(
                        org_id=org.id, product_category_id=item.id,
                        source=DataSource.INTERNAL_VERIFIED,
                    )
                    db.add(capability)
                    db.flush()
                if cell("notes"):
                    capability.notes = str(cell("notes")).strip()

                from app.models import SupplierCapabilityFibre

                for fibre in fibre_items:
                    exists = db.scalars(
                        select(SupplierCapabilityFibre).where(
                            SupplierCapabilityFibre.capability_id == capability.id,
                            SupplierCapabilityFibre.fibre_id == fibre.id,
                        )
                    ).first()
                    if exists is None:
                        db.add(
                            SupplierCapabilityFibre(
                                capability_id=capability.id, fibre_id=fibre.id
                            )
                        )

            db.flush()
            completeness.refresh_supplier(db, org)

            if is_new:
                created += 1
            else:
                updated += 1

            savepoint.commit()

            note = "queued for taxonomy review: " + ", ".join(unresolved) if unresolved else None
            results.append({
                "row": row_number, "status": "created" if is_new else "updated",
                "org_id": str(org.id), "name": factory_name, "message": note,
            })

        except Exception as exc:  # noqa: BLE001 - one bad row must not lose the other 199
            savepoint.rollback()
            errors += 1
            results.append({
                "row": row_number, "status": "error", "name": factory_name,
                "message": str(exc)[:300],
            })

    batch.total_rows = len(results)
    batch.created_count = created
    batch.updated_count = updated
    batch.error_count = errors
    batch.row_results = results
    batch.completed_at = datetime.now(timezone.utc)

    if dry_run:
        # Keep nothing at all, including the batch record — a dry run must leave no trace.
        db.rollback()
        return {
            "dry_run": True, "total_rows": len(results), "created": created,
            "updated": updated, "errors": errors, "rows": results,
        }

    activity.record(
        db, entity_type="ImportBatch", entity_id=batch.id, action=ActivityAction.BULK_IMPORT,
        actor=principal,
        summary=f"Imported {file.filename}: {created} created, {updated} updated, {errors} errors",
    )
    db.commit()

    return {
        "dry_run": False, "batch_id": str(batch.id), "total_rows": len(results),
        "created": created, "updated": updated, "errors": errors, "rows": results,
    }


@router.get("/{batch_id}")
def get_batch(
    batch_id: uuid.UUID,
    principal: Principal = Depends(require_internal),
    db: Session = Depends(get_db),
) -> dict:
    """Per-row outcome of a past import, so a bad sheet can be audited after the fact."""
    require(principal, Action.VIEW_INTERNAL, "ImportBatch")

    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    return {
        "id": str(batch.id), "filename": batch.filename, "total_rows": batch.total_rows,
        "created": batch.created_count, "updated": batch.updated_count,
        "errors": batch.error_count, "rows": batch.row_results or [],
        "completed_at": batch.completed_at,
    }
