"""Shared schema building blocks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base for request bodies: unknown fields are an error, not a shrug."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    """Base for responses; reads attributes straight off ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """The single error envelope every failing request returns."""

    error: ErrorDetail


class Page[T](ResponseModel):
    """Cursor-paginated collection."""

    items: list[T]
    next_cursor: str | None = None
