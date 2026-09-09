"""Files, grouped into a folder per deal.

Uploads land on local disk under a directory per deal. That is deliberate: at this size an S3
bucket is operational overhead, and a folder on the machine is something you can also open in
Finder when the app is not running.
"""
from __future__ import annotations

import hashlib
import pathlib
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.config import settings
from app.db import SessionLocal, get_db
from app.enums import ActivityAction, DocumentKind
from app.models import ActivityLog, Company, Deal, Document, User
from app.services.ingest import ingest_document
from app.schemas import DocOut, Msg

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_BYTES = 40 * 1024 * 1024


def _root() -> pathlib.Path:
    root = pathlib.Path(settings.file_storage_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.get("", response_model=list[DocOut])
def list_documents(
    deal_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[DocOut]:
    if deal_id is None and company_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="Ask for a deal's folder or a company's files")
    stmt = select(Document)
    if deal_id:
        stmt = stmt.where(Document.deal_id == deal_id)
    if company_id:
        stmt = stmt.where(Document.company_id == company_id)
    rows = db.scalars(stmt.order_by(Document.created_at.desc())).all()
    return [DocOut.model_validate(r) for r in rows]


@router.post("", response_model=DocOut, status_code=201)
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    kind: DocumentKind = Form(DocumentKind.OTHER),
    deal_id: uuid.UUID | None = Form(None),
    company_id: uuid.UUID | None = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DocOut:
    if deal_id is None and company_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="A file has to belong to a deal or a company")
    if deal_id and db.get(Deal, deal_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such deal")
    if company_id and db.get(Company, company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such company")

    payload = await file.read()
    if len(payload) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=f"Files are limited to {MAX_BYTES // 1024 // 1024} MB")
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="That file is empty")

    folder = _root() / (f"deal-{deal_id}" if deal_id else f"company-{company_id}")
    folder.mkdir(parents=True, exist_ok=True)

    # Content hash in the stored name: re-uploading the same PDF cannot collide, and a
    # user-supplied filename never reaches the filesystem.
    digest = hashlib.sha256(payload).hexdigest()[:16]
    suffix = pathlib.Path(file.filename or "").suffix[:12]
    stored = folder / f"{digest}{suffix}"
    stored.write_bytes(payload)

    doc = Document(
        deal_id=deal_id, company_id=company_id, kind=kind,
        title=title or file.filename or "Untitled",
        storage_key=str(stored.relative_to(_root())),
        original_filename=file.filename, content_type=file.content_type,
        size_bytes=len(payload), uploaded_by_user_id=user.id,
    )
    db.add(doc)
    db.add(ActivityLog(entity_type="Document", entity_id=doc.id, deal_id=deal_id,
                       company_id=company_id, actor_user_id=user.id, actor_label=user.name,
                       action=ActivityAction.UPLOAD, summary=f"Uploaded {doc.title}"))
    db.commit()
    db.refresh(doc)

    # Extract, chunk and embed after the response goes out. The upload should not wait on a
    # PDF parse, and a failure here is recorded on the document rather than losing the file.
    background.add_task(_ingest_later, doc.id)
    return DocOut.model_validate(doc)


def _ingest_later(document_id: uuid.UUID) -> None:
    """Runs after the response. Needs its own session — the request's is closed by then."""
    db = SessionLocal()
    try:
        ingest_document(db, document_id)
    finally:
        db.close()


@router.get("/{document_id}/download")
def download(document_id: uuid.UUID, _: User = Depends(current_user),
             db: Session = Depends(get_db)) -> FileResponse:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    path = (_root() / doc.storage_key).resolve()
    # The stored key is ours, but resolving it back under the root costs nothing and stops a
    # crafted key ever escaping the directory.
    if not str(path).startswith(str(_root().resolve())) or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="The file is missing from disk")

    return FileResponse(path, filename=doc.original_filename or doc.title,
                        media_type=doc.content_type or "application/octet-stream")


@router.delete("/{document_id}", response_model=Msg)
def delete_document(document_id: uuid.UUID, _: User = Depends(current_user),
                    db: Session = Depends(get_db)) -> Msg:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    path = (_root() / doc.storage_key).resolve()
    if str(path).startswith(str(_root().resolve())) and path.exists():
        path.unlink()
    db.delete(doc)
    db.commit()
    return Msg(detail="Deleted")
