"""Gather the facts a week's League Points are computed from.

This is the only place that reads the database on behalf of scoring. The scorer itself is
pure (`app/domain/scoring/`), so keeping collection separate is what makes a past week
reproducible: store these inputs, replay them through the season's frozen config, get the
identical score months later (ADR-0006).

Every number here is deliberately the *competitive* view of the week: manual time is reported
but never counted, and integrity-flagged time is excluded with its reasons carried through so
the user can be told exactly what was left out.
"""

from __future__ import annotations

import uuid
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import ensure_utc
from app.domain.scoring.models import DayActivity, WeeklyScoreInput
from app.domain.statistics.calendar import range_window, resolve_timezone, week_bounds
from app.domain.statistics.service import StatisticsService
from app.models.enums import (
    FocusMode,
    IntegrityStatus,
    SessionSource,
    SessionStatus,
    TaskStatus,
)
from app.models.planner import DailyPlan, Task
from app.models.social import Encouragement
from app.models.study import StudySession
from app.models.user import User


class LeagueFactsService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._statistics = StatisticsService(db)

    async def weekly_input(self, *, user: User, week_start: date) -> WeeklyScoreInput:
        """Build one user's scoring input for the week containing `week_start`."""
        tz = resolve_timezone(user.settings.timezone)
        first_day, last_day = week_bounds(week_start)

        weekly = await self._statistics.weekly_summary(
            user_id=user.id,
            anchor_day=first_day,
            tz=tz,
            daily_goal_minutes=user.settings.daily_goal_minutes,
            weekly_goal_minutes=user.settings.weekly_goal_minutes,
            scheduled_days_mask=user.settings.scheduled_study_days,
        )

        days = tuple(
            DayActivity(
                day=totals.day,
                is_scheduled=totals.is_scheduled,
                verified_seconds=totals.verified_seconds,
                manual_seconds=totals.manual_seconds,
                excluded_seconds=totals.excluded_seconds,
                goal_minutes=totals.goal_minutes,
            )
            for totals in weekly.days
        )

        focus = await self._focus_sessions_completed(user.id, first_day, last_day, tz)
        planned, completed = await self._task_counts(user.id, first_day, last_day)
        participation = await self._participation_events(user.id, first_day, last_day, tz)
        reasons = await self._exclusion_reasons(user.id, first_day, last_day, tz)

        return WeeklyScoreInput(
            user_id=str(user.id),
            week_start=first_day,
            days=days,
            focus_sessions_completed=focus,
            tasks_planned=planned,
            tasks_completed=completed,
            participation_events=participation,
            excluded_seconds=weekly.excluded_seconds,
            exclusion_reasons=reasons,
        )

    async def early_sessions_completed(
        self, *, user: User, week_start: date, before_hour: int = 12
    ) -> int:
        """Completed sessions the user *started* before `before_hour`, in their own zone."""
        tz = resolve_timezone(user.settings.timezone)
        first_day, last_day = week_bounds(week_start)
        window = range_window(first_day, last_day, tz)
        result = await self._db.execute(
            select(StudySession.started_at).where(
                StudySession.user_id == user.id,
                StudySession.status == SessionStatus.COMPLETED.value,
                StudySession.source == SessionSource.TIMER.value,
                StudySession.integrity_status == IntegrityStatus.OK.value,
                StudySession.started_at >= window.start,
                StudySession.started_at < window.end,
            )
        )
        return sum(
            1
            for started_at in result.scalars().all()
            if ensure_utc(started_at).astimezone(tz).hour < before_hour
        )

    async def _focus_sessions_completed(
        self, user_id: uuid.UUID, first_day: date, last_day: date, tz: ZoneInfo
    ) -> int:
        """Finished Pomodoro blocks, plus stopwatch sessions the user marked as going to plan.

        "Completed" means the user finished what they set out to do — not merely that time
        elapsed — which is why a stopwatch session only counts when explicitly marked.
        """
        window = range_window(first_day, last_day, tz)
        result = await self._db.execute(
            select(func.count())
            .select_from(StudySession)
            .where(
                StudySession.user_id == user_id,
                StudySession.status == SessionStatus.COMPLETED.value,
                StudySession.source == SessionSource.TIMER.value,
                StudySession.integrity_status == IntegrityStatus.OK.value,
                StudySession.started_at >= window.start,
                StudySession.started_at < window.end,
                (StudySession.focus_mode == FocusMode.POMODORO.value)
                | (StudySession.went_as_planned.is_(True)),
            )
        )
        return int(result.scalar_one())

    async def _task_counts(
        self, user_id: uuid.UUID, first_day: date, last_day: date
    ) -> tuple[int, int]:
        """Planned vs completed tasks across the week's daily plans."""
        result = await self._db.execute(
            select(Task.status)
            .join(DailyPlan, Task.plan_id == DailyPlan.id)
            .where(
                DailyPlan.user_id == user_id,
                DailyPlan.plan_date >= first_day,
                DailyPlan.plan_date <= last_day,
            )
        )
        statuses = list(result.scalars().all())
        completed = sum(1 for status in statuses if status == TaskStatus.DONE.value)
        return len(statuses), completed

    async def _participation_events(
        self, user_id: uuid.UUID, first_day: date, last_day: date, tz: ZoneInfo
    ) -> int:
        """Encouragement sent to others. Capped low by the scorer, and deliberately
        counts *giving* rather than receiving so it cannot be farmed by being popular."""
        window = range_window(first_day, last_day, tz)
        result = await self._db.execute(
            select(func.count())
            .select_from(Encouragement)
            .where(
                Encouragement.from_user_id == user_id,
                Encouragement.created_at >= window.start,
                Encouragement.created_at < window.end,
            )
        )
        return int(result.scalar_one())

    async def _exclusion_reasons(
        self, user_id: uuid.UUID, first_day: date, last_day: date, tz: ZoneInfo
    ) -> tuple[str, ...]:
        """Distinct integrity reasons behind any time excluded this week."""
        window = range_window(first_day, last_day, tz)
        result = await self._db.execute(
            select(StudySession.integrity_reasons).where(
                StudySession.user_id == user_id,
                StudySession.status == SessionStatus.COMPLETED.value,
                StudySession.integrity_status != IntegrityStatus.OK.value,
                StudySession.started_at >= window.start,
                StudySession.started_at < window.end,
            )
        )
        reasons: set[str] = set()
        for stored in result.scalars().all():
            if isinstance(stored, list):
                reasons.update(str(reason) for reason in stored)
        return tuple(sorted(reasons))
