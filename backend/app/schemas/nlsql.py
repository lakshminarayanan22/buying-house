"""Natural-language record editor schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProposeBody(BaseModel):
    """Describe the change in English, or supply SQL directly.

    `sql` exists because the planner is a convenience, not the feature. A Super Admin who
    already knows the statement should not have to phrase it as a sentence and hope — and the
    guard, the preview and the confirm step apply identically either way.
    """

    prompt: str = Field(min_length=3, max_length=2000)
    sql: str | None = Field(None, max_length=8000)
    max_rows: int | None = Field(None, ge=1, le=5000)


class ChangeCell(BaseModel):
    before: object | None = None
    after: object | None = None


class ChangeRow(BaseModel):
    pk: list[str]
    operation: str
    before: dict | None = None
    after: dict | None = None
    # column -> {before, after}. This is what the UI highlights.
    changes: dict[str, ChangeCell] = {}


class ChangePreview(ORMModel):
    id: uuid.UUID
    prompt: str
    generated_sql: str
    explanation: str | None
    target_table: str
    statement_kind: str
    affected_count: int
    diff: list[ChangeRow] | None
    status: str
    planner_backend: str
    planner_model: str | None
    expires_at: datetime | None
    created_at: datetime


class ChangeApplied(ORMModel):
    id: uuid.UUID
    status: str
    target_table: str
    affected_count: int
    applied_at: datetime | None


class ClarificationNeeded(BaseModel):
    """Returned when the request was too ambiguous to turn into a statement."""

    needs_clarification: bool = True
    question: str
