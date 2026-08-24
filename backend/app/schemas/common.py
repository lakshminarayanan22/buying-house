"""Shared response shapes."""
from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class IdResponse(BaseModel):
    id: uuid.UUID


class Message(BaseModel):
    detail: str
