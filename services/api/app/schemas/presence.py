"""Presence contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from app.schemas.common import ResponseModel, StrictModel
from app.schemas.social import PublicUserResponse

PresenceStateLiteral = Literal["studying", "break", "idle"]


class HeartbeatRequest(StrictModel):
    state: PresenceStateLiteral
    subject_id: uuid.UUID | None = None
    started_at: datetime | None = None


class PresenceResponse(ResponseModel):
    user: PublicUserResponse
    state: str
    subject_id: uuid.UUID | None = None
    started_at: datetime | None = None
    updated_at: datetime
