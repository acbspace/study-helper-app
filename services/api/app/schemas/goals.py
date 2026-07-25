"""D-Day goal contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel

GoalStatus = Literal["active", "completed", "archived"]


class MilestoneInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    target_date: date | None = None
    done: bool = False


class MilestoneResponse(ResponseModel):
    title: str
    target_date: str | None = None
    done: bool = False


class CreateGoalRequest(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    target_date: date | None = None
    target_weekly_minutes: int = Field(default=0, ge=0, le=10080)
    subject_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    milestones: list[MilestoneInput] = Field(default_factory=list, max_length=20)
    description: str | None = Field(default=None, max_length=2000)


class UpdateGoalRequest(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    target_date: date | None = None
    clear_target_date: bool = False
    target_weekly_minutes: int | None = Field(default=None, ge=0, le=10080)
    subject_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    milestones: list[MilestoneInput] | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=2000)
    status: GoalStatus | None = None


class GoalResponse(ResponseModel):
    id: uuid.UUID
    title: str
    target_date: date | None = None
    target_weekly_minutes: int
    subject_ids: list[str]
    milestones: list[MilestoneResponse]
    description: str | None = None
    status: str
    completed_at: datetime | None = None
    # Computed pacing.
    days_remaining: int | None = None
    is_overdue: bool = False
    week_verified_minutes: int = 0
    weekly_progress: float = 0.0
    milestones_total: int = 0
    milestones_done: int = 0
