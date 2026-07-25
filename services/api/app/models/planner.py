"""Daily plans, tasks, and reflections."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UtcDateTime, UuidType
from app.models.enums import TaskPriority, TaskStatus


class DailyPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One plan per user per local calendar date.

    `plan_date` is the user's local date (not UTC): a plan belongs to the day the user
    experienced, which is why aggregation converts through their time zone.
    """

    __tablename__ = "daily_plans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)

    # `foreign_keys` is required because Task points here twice: once for the plan it
    # belongs to, and once for the plan a deferred task was pushed to.
    tasks: Mapped[list[Task]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="Task.sort_order",
        foreign_keys="Task.plan_id",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "plan_date", name="uq_daily_plans_user_date"),
        Index("ix_daily_plans_user_date", "user_id", "plan_date"),
    )


class Task(Base, TimestampMixin):
    """A planned unit of work. Client-generated id so tasks can be created offline."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[str] = mapped_column(
        String(8), nullable=False, default=TaskPriority.NORMAL.value
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=TaskStatus.PENDING.value
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    deferred_to_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("daily_plans.id", ondelete="SET NULL"), nullable=True
    )

    plan: Mapped[DailyPlan] = relationship(back_populates="tasks", foreign_keys=[plan_id])

    __table_args__ = (
        CheckConstraint("estimated_minutes BETWEEN 0 AND 1440", name="ck_tasks_estimate_range"),
        CheckConstraint(
            "status <> 'done' OR completed_at IS NOT NULL", name="ck_tasks_done_has_timestamp"
        ),
    )
