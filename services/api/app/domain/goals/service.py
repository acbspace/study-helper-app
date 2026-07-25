"""D-Day goals: long-horizon commitments with a countdown and weekly pacing.

A goal answers "am I on track?", not "how many hours did I grind?". So the progress this
service computes is measured against the *weekly commitment the user set for themselves* and
uses **verified** time only — the same honesty rule the league applies. The countdown to the
target date is the emotional core of the feature, so it is always present when a date is set,
even after the day passes (a goal can be overdue, and pretending otherwise would be a lie).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.errors import ErrorCode, NotFoundError
from app.domain.statistics.calendar import range_window, resolve_timezone, week_bounds
from app.models.enums import IntegrityStatus, SessionSource, SessionStatus
from app.models.study import StudyGoal, StudySession
from app.models.user import User

GOAL_ACTIVE = "active"
GOAL_COMPLETED = "completed"
GOAL_ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class GoalProgress:
    goal: StudyGoal
    days_remaining: int | None
    is_overdue: bool
    week_verified_minutes: int
    weekly_progress: float
    milestones_total: int
    milestones_done: int


class GoalService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for(self, user: User, *, include_finished: bool = False) -> list[GoalProgress]:
        query = select(StudyGoal).where(StudyGoal.user_id == user.id)
        if not include_finished:
            query = query.where(StudyGoal.status == GOAL_ACTIVE)
        result = await self._db.execute(query.order_by(StudyGoal.created_at.desc()))
        goals = list(result.scalars().all())
        return [await self._with_progress(user, goal) for goal in goals]

    async def get_owned(self, user: User, goal_id: uuid.UUID) -> GoalProgress:
        goal = await self._require(user.id, goal_id)
        return await self._with_progress(user, goal)

    async def create(
        self,
        *,
        user: User,
        title: str,
        target_date: date | None,
        target_weekly_minutes: int,
        subject_ids: Sequence[uuid.UUID],
        milestones: Sequence[dict[str, Any]],
        description: str | None,
    ) -> GoalProgress:
        goal = StudyGoal(
            user_id=user.id,
            title=title.strip(),
            target_date=target_date,
            target_weekly_minutes=target_weekly_minutes,
            subject_ids=[str(subject_id) for subject_id in subject_ids],
            milestones=_normalise_milestones(milestones),
            description=description,
            status=GOAL_ACTIVE,
        )
        self._db.add(goal)
        await self._db.commit()
        await self._db.refresh(goal)
        return await self._with_progress(user, goal)

    async def update(
        self,
        *,
        user: User,
        goal_id: uuid.UUID,
        title: str | None = None,
        target_date: date | None = None,
        clear_target_date: bool = False,
        target_weekly_minutes: int | None = None,
        subject_ids: Sequence[uuid.UUID] | None = None,
        milestones: Sequence[dict[str, Any]] | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> GoalProgress:
        goal = await self._require(user.id, goal_id)
        if title is not None:
            goal.title = title.strip()
        if clear_target_date:
            goal.target_date = None
        elif target_date is not None:
            goal.target_date = target_date
        if target_weekly_minutes is not None:
            goal.target_weekly_minutes = target_weekly_minutes
        if subject_ids is not None:
            goal.subject_ids = [str(subject_id) for subject_id in subject_ids]
        if milestones is not None:
            goal.milestones = _normalise_milestones(milestones)
        if description is not None:
            goal.description = description
        if status is not None:
            goal.status = status
            goal.completed_at = utc_now() if status == GOAL_COMPLETED else None

        await self._db.commit()
        await self._db.refresh(goal)
        return await self._with_progress(user, goal)

    async def delete(self, *, user_id: uuid.UUID, goal_id: uuid.UUID) -> None:
        goal = await self._require(user_id, goal_id)
        await self._db.delete(goal)
        await self._db.commit()

    # ------------------------------------------------------------------ helpers

    async def _require(self, user_id: uuid.UUID, goal_id: uuid.UUID) -> StudyGoal:
        result = await self._db.execute(
            select(StudyGoal).where(StudyGoal.id == goal_id, StudyGoal.user_id == user_id)
        )
        goal = result.scalar_one_or_none()
        if goal is None:
            raise NotFoundError(ErrorCode.GOAL_NOT_FOUND, "Goal not found.")
        return goal

    async def _with_progress(self, user: User, goal: StudyGoal) -> GoalProgress:
        tz = resolve_timezone(user.settings.timezone)
        today = utc_now().astimezone(tz).date()

        days_remaining: int | None = None
        is_overdue = False
        if goal.target_date is not None:
            days_remaining = (goal.target_date - today).days
            is_overdue = days_remaining < 0 and goal.status == GOAL_ACTIVE

        week_minutes = await self._week_verified_minutes(user.id, today, goal.subject_ids, tz)
        weekly_progress = (
            0.0
            if goal.target_weekly_minutes <= 0
            else round(min(week_minutes / goal.target_weekly_minutes, 1.0), 4)
        )

        milestones = goal.milestones or []
        done = sum(1 for milestone in milestones if milestone.get("done"))
        return GoalProgress(
            goal=goal,
            days_remaining=days_remaining,
            is_overdue=is_overdue,
            week_verified_minutes=week_minutes,
            weekly_progress=weekly_progress,
            milestones_total=len(milestones),
            milestones_done=done,
        )

    async def _week_verified_minutes(
        self,
        user_id: uuid.UUID,
        today: date,
        subject_ids: list[str],
        tz: ZoneInfo,
    ) -> int:
        """Verified minutes this local week, optionally limited to the goal's subjects."""
        first_day, last_day = week_bounds(today)
        window = range_window(first_day, last_day, tz)
        query = select(func.coalesce(func.sum(StudySession.duration_seconds), 0)).where(
            StudySession.user_id == user_id,
            StudySession.status == SessionStatus.COMPLETED.value,
            StudySession.source == SessionSource.TIMER.value,
            StudySession.integrity_status == IntegrityStatus.OK.value,
            StudySession.started_at >= window.start,
            StudySession.started_at < window.end,
        )
        if subject_ids:
            query = query.where(
                StudySession.subject_id.in_([uuid.UUID(sid) for sid in subject_ids])
            )
        result = await self._db.execute(query)
        return int(result.scalar_one()) // 60


def _normalise_milestones(milestones: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the fields a milestone owns, so arbitrary client JSON cannot ride along."""
    cleaned: list[dict[str, Any]] = []
    for milestone in milestones:
        title = str(milestone.get("title", "")).strip()
        if not title:
            continue
        entry: dict[str, Any] = {"title": title[:120], "done": bool(milestone.get("done", False))}
        due = milestone.get("target_date")
        if isinstance(due, str) and due:
            entry["target_date"] = due
        cleaned.append(entry)
    return cleaned
