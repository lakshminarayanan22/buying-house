"""Taxonomy schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.enums import ReferenceDomain
from app.schemas.common import ORMModel


class ReferenceItemOut(ORMModel):
    id: uuid.UUID
    domain: ReferenceDomain
    code: str
    name: str
    description: str | None = None
    parent_id: uuid.UUID | None = None
    path: str
    depth: int
    sort_order: int
    is_active: bool


class ReferenceItemWithAliases(ReferenceItemOut):
    aliases: list[str] = []


class ReferenceItemCreate(BaseModel):
    domain: ReferenceDomain
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int = 0
    aliases: list[str] = []


class ReferenceItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=160)
    language: str = "en"


class UnmappedTermOut(ORMModel):
    id: uuid.UUID
    domain: ReferenceDomain
    raw_text: str
    normalised: str
    occurrences: int
    source_entity_type: str | None = None
    resolved_item_id: uuid.UUID | None = None


class ResolveUnmappedBody(BaseModel):
    """Map a queued term onto an existing value, or promote it into a new one."""

    item_id: uuid.UUID | None = None
    new_code: str | None = Field(None, max_length=60)
    new_name: str | None = Field(None, max_length=160)
    parent_id: uuid.UUID | None = None
