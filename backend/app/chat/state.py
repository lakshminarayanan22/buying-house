"""Shared state and the classifier's output shape."""
from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class Category(StrEnum):
    DATABASE = "DATABASE"
    TECHNICAL = "TECHNICAL"
    CREATIVE = "CREATIVE"
    # Not a fourth thing the app can do — the absence of the other three. Having a name for it
    # is what lets the graph decline instead of guessing which branch is least wrong.
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class QueryClassification(BaseModel):
    """What the classifier returns. Every field is here for a reason.

    `secondary` because real questions span categories — "who does cooling finishes, and what
    do we owe them" is TECHNICAL and DATABASE, and a single label has to pick one and be half
    wrong. `confidence` because a clarifying question is cheaper than a wrong branch.
    `reasoning` because when the eval set shows a misroute, a bare label is not debuggable.
    """

    primary: Category
    secondary: Category | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class ChatState(TypedDict, total=False):
    """Carried through the graph.

    `user_role` comes from the session and is read by the DATABASE branch to decide whether the
    write tool exists at all. It is never derived from the message or from the classification.
    """

    question: str
    page_context: str | None
    user_id: str
    user_role: Literal["ADMIN", "MEMBER"]

    classification: QueryClassification | None
    retrieved: list[Any]
    sql: str | None
    sql_rows: list[dict] | None
    pending_write: dict | None
    citations: list[str]
    answer: str | None
    needs_clarification: str | None
    trace: list[str]
