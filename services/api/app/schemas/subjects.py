"""Subject contracts."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel

ColorHex = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class SubjectResponse(ResponseModel):
    id: uuid.UUID
    name: str
    color_hex: str
    sort_order: int
    is_archived: bool


class CreateSubjectRequest(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    color_hex: ColorHex = "#4F6BED"
    sort_order: int | None = Field(default=None, ge=0)


class UpdateSubjectRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    color_hex: ColorHex | None = None
    sort_order: int | None = Field(default=None, ge=0)
    is_archived: bool | None = None


class ReorderSubjectsRequest(StrictModel):
    subject_ids: list[uuid.UUID] = Field(min_length=1)
