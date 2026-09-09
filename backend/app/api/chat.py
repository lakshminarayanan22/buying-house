"""The chatbot's HTTP surface."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.chat import answer
from app.chat.branches import apply_write
from app.chat.llm import is_stub
from app.config import settings
from app.db import get_db
from app.enums import ActivityAction, UserRole
from app.models import ActivityLog, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

# A previewed write, held until the user confirms. In memory because a preview is only valid
# for the few seconds a person spends reading a diff; surviving a restart is not a feature.
_PENDING: dict[str, dict] = {}


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    # What the user is looking at. The composer is on every screen, so "what's outstanding on
    # this one" should work without naming the deal. Kept out of the stored question so the
    # transcript reads as the person actually typed it.
    context: str | None = Field(None, max_length=400)


class AskResponse(BaseModel):
    answer: str
    category: str | None = None
    secondary: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    citations: list[str] = []
    sql: str | None = None
    rows: list[dict] | None = None
    pending_write_id: str | None = None
    pending_write: dict | None = None
    needs_clarification: bool = False
    backend: str


@router.post("/ask", response_model=AskResponse)
def ask(body: AskBody, user: User = Depends(current_user),
        db: Session = Depends(get_db)) -> AskResponse:
    try:
        state = answer(body.question, user_id=str(user.id), user_role=user.role,
                       context=body.context)
    except Exception as exc:  # noqa: BLE001 - a model or query failure is a 400, not a 500
        logger.exception("chat failed")
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f"{type(exc).__name__}: {exc}")

    classification = state.get("classification")
    pending_id = None
    if state.get("pending_write"):
        pending_id = uuid.uuid4().hex
        _PENDING[pending_id] = {
            "pending": state["pending_write"], "question": body.question,
            "user_id": str(user.id),
        }

    # The classifier is a component that can be wrong, so it has to be a component you can
    # audit. Question, label, confidence and reasoning all land in the trail.
    db.add(ActivityLog(
        entity_type="Chat", actor_user_id=user.id, actor_label=user.name,
        action=ActivityAction.NOTE,
        summary=f"Q: {body.question[:200]}",
        after={
            "category": classification.primary.value if classification else None,
            "secondary": classification.secondary.value
                         if classification and classification.secondary else None,
            "confidence": classification.confidence if classification else None,
            "reasoning": classification.reasoning if classification else None,
            "sql": state.get("sql"),
            "citations": state.get("citations") or [],
            "trace": state.get("trace") or [],
            "backend": settings.llm_backend,
        },
    ))
    db.commit()

    return AskResponse(
        answer=state.get("answer") or "",
        category=classification.primary.value if classification else None,
        secondary=classification.secondary.value
                  if classification and classification.secondary else None,
        confidence=classification.confidence if classification else None,
        reasoning=classification.reasoning if classification else None,
        citations=state.get("citations") or [],
        sql=state.get("sql"),
        rows=state.get("sql_rows"),
        pending_write_id=pending_id,
        pending_write=state.get("pending_write"),
        needs_clarification=bool(state.get("needs_clarification")),
        backend=settings.llm_backend,
    )


@router.post("/confirm/{pending_id}")
def confirm(pending_id: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)) -> dict:
    """Commit a previewed write. Admins only — the same rule the branch applies."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admins only")

    held = _PENDING.pop(pending_id, None)
    if held is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail="That preview has expired. Ask again to see a fresh diff.")

    try:
        result = apply_write(held["pending"], actor_id=user.id, question=held["question"])
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return result


@router.post("/discard/{pending_id}")
def discard(pending_id: str, _: User = Depends(current_user)) -> dict:
    _PENDING.pop(pending_id, None)
    return {"discarded": True}


@router.get("/health")
def chat_health(_: User = Depends(current_user)) -> dict:
    """What the chatbot is actually running on, so a stub answer is never mistaken for real."""
    from app.retrieval.embedding import active_model

    return {
        "llm_backend": settings.llm_backend,
        "is_stub": is_stub(),
        "classifier_model": settings.classifier_model,
        "branch_model": settings.branch_model,
        "embedding_backend": settings.embedding_backend,
        "embedding_model": active_model(),
        "similarity_floor": settings.similarity_floor,
        "readonly_role_configured": bool(settings.database_url_readonly),
    }
