"""Report and notification contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel
from app.schemas.social import PublicUserResponse

ReportSubject = Literal["user", "group", "post", "comment"]


class CreateReportRequest(StrictModel):
    subject_type: ReportSubject
    subject_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)


class ReportResponse(ResponseModel):
    id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    reason: str
    status: str
    created_at: datetime


class NotificationResponse(ResponseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    data: dict[str, Any]
    read_at: datetime | None = None
    created_at: datetime


class UnreadCountResponse(ResponseModel):
    unread: int


class PushTokenRequest(StrictModel):
    token: str = Field(min_length=1, max_length=255)
    platform: Literal["ios", "android", "web", "unknown"] = "unknown"


# --- moderation (admin only) ---


class ModerationReportResponse(ResponseModel):
    id: uuid.UUID
    reporter: PublicUserResponse | None = None
    subject_type: str
    subject_id: uuid.UUID
    subject_preview: str | None = None
    reason: str
    status: str
    resolution_note: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class ResolveReportRequest(StrictModel):
    decision: Literal["dismiss", "action"]
    # Only meaningful when decision is "action" and the subject is a post or comment.
    remove_content: bool = False
    note: str | None = Field(default=None, max_length=1000)
