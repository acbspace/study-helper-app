"""Daily plan and task contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.common import ResponseModel, StrictModel


class TaskResponse(ResponseModel):
    id: uuid.UUID
    subject_id: uuid.UUID | None
    title: str
    estimated_minutes: int
    priority: TaskPriority
    status: TaskStatus
    sort_order: int
    completed_at: datetime | None


class DailyPlanResponse(ResponseModel):
    id: uuid.UUID
    plan_date: date
    reflection: str | None
    tasks: list[TaskResponse]


class CreateTaskRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    # Client-supplied id keeps offline-created tasks stable across sync.
    task_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    estimated_minutes: int = Field(default=0, ge=0, le=1440)
    priority: TaskPriority = TaskPriority.NORMAL
    sort_order: int | None = Field(default=None, ge=0)


class UpdateTaskRequest(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subject_id: uuid.UUID | None = None
    estimated_minutes: int | None = Field(default=None, ge=0, le=1440)
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ReflectionRequest(StrictModel):
    reflection: str | None = Field(default=None, max_length=4000)


class CarryForwardRequest(StrictModel):
    to_date: date
