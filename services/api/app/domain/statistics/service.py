"""Study statistics: daily and weekly summaries, subject breakdowns, and streaks.

Sessions are fetched by UTC window and bucketed into user-local days in Python (ADR-0003):
portable across engines and easy to test. Verified and manual time are always reported
separately — conflating them is exactly what makes leaderboards untrustworthy.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import ensure_utc
from app.domain.statistics.calendar import (
    day_window,
    days_in_range,
    is_scheduled_day,
    local_date_of,
    range_window,
    week_bounds,
)
from app.models.enums import IntegrityStatus, SessionSource, SessionStatus, TaskStatus
from app.models.planner import DailyPlan, Task
from app.models.study import StudySession, Subject


@dataclass(frozen=True, slots=True)
class SubjectTotal:
    subject_id: uuid.UUID
    name: str
    color_hex: str
    verified_seconds: int
    manual_seconds: int

    @property
    def total_seconds(self) -> int:
        return self.verified_seconds + self.manual_seconds


@dataclass(frozen=True, slots=True)
class DayTotals:
    day: date
    verified_seconds: int
    manual_seconds: int
    excluded_seconds: int
    session_count: int
    is_scheduled: bool
    goal_minutes: int

    @property
    def total_seconds(self) -> int:
        return self.verified_seconds + self.manual_seconds

    @property
    def goal_met(self) -> bool:
        # Only verified time counts toward the goal — this is the same rule the league uses.
        return self.goal_minutes > 0 and self.verified_seconds >= self.goal_minutes * 60


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: date
    timezone: str
    verified_seconds: int
    manual_seconds: int
    excluded_seconds: int
    goal_minutes: int
    goal_progress: float
    session_count: int
    subjects: list[SubjectTotal] = field(default_factory=list)
    tasks_total: int = 0
    tasks_completed: int = 0
    planned_minutes: int = 0
    current_streak_days: int = 0

    @property
    def total_seconds(self) -> int:
        return self.verified_seconds + self.manual_seconds


@dataclass(frozen=True, slots=True)
class HeatmapDay:
    day: date
    verified_seconds: int
    goal_met: bool


@dataclass(frozen=True, slots=True)
class MonthTotals:
    month: str  # "YYYY-MM"
    verified_seconds: int
    session_count: int
    active_days: int


@dataclass(frozen=True, slots=True)
class YearlyInsights:
    year: int
    timezone: str
    verified_seconds: int
    manual_seconds: int
    session_count: int
    active_days: int
    longest_streak_days: int
    busiest_day: date | None
    months: list[MonthTotals]
    heatmap: list[HeatmapDay]
    subjects: list[SubjectTotal]

    @property
    def total_seconds(self) -> int:
        return self.verified_seconds + self.manual_seconds


@dataclass(frozen=True, slots=True)
class WeeklySummary:
    week_start: date
    week_end: date
    timezone: str
    verified_seconds: int
    manual_seconds: int
    excluded_seconds: int
    goal_minutes: int
    days: list[DayTotals]
    subjects: list[SubjectTotal]
    scheduled_days: int
    scheduled_days_met: int
    average_session_seconds: int
    session_count: int

    @property
    def total_seconds(self) -> int:
        return self.verified_seconds + self.manual_seconds

    @property
    def goal_completion_rate(self) -> float:
        if self.scheduled_days == 0:
            return 0.0
        return round(self.scheduled_days_met / self.scheduled_days, 4)


class StatisticsService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _sessions_between(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[StudySession]:
        """Completed sessions whose start falls in the window.

        Attribution rule: a session belongs to the local day it *started* on. Splitting
        across midnight would be more precise but makes "when did I study" confusing and
        breaks streak intuition, so we attribute whole sessions to their start day.
        """
        result = await self._db.execute(
            select(StudySession).where(
                StudySession.user_id == user_id,
                StudySession.status == SessionStatus.COMPLETED.value,
                StudySession.started_at >= start,
                StudySession.started_at < end,
            )
        )
        return list(result.scalars().all())

    async def _subject_lookup(self, user_id: uuid.UUID) -> dict[uuid.UUID, Subject]:
        result = await self._db.execute(select(Subject).where(Subject.user_id == user_id))
        return {subject.id: subject for subject in result.scalars().all()}

    async def daily_summary(
        self,
        *,
        user_id: uuid.UUID,
        day: date,
        tz: ZoneInfo,
        goal_minutes: int,
        scheduled_days_mask: int,
    ) -> DailySummary:
        window = day_window(day, tz)
        sessions = await self._sessions_between(user_id, window.start, window.end)
        subjects = await self._subject_lookup(user_id)

        verified, manual, excluded = _split_seconds(sessions)
        subject_totals = _subject_totals(sessions, subjects)
        tasks_total, tasks_completed, planned_minutes = await self._task_totals(user_id, day)
        streak = await self.current_streak(
            user_id=user_id,
            today=day,
            tz=tz,
            goal_minutes=goal_minutes,
            scheduled_days_mask=scheduled_days_mask,
        )

        progress = 0.0 if goal_minutes <= 0 else round(verified / (goal_minutes * 60), 4)
        return DailySummary(
            day=day,
            timezone=str(tz),
            verified_seconds=verified,
            manual_seconds=manual,
            excluded_seconds=excluded,
            goal_minutes=goal_minutes,
            goal_progress=min(progress, 1.0) if goal_minutes > 0 else 0.0,
            session_count=len(sessions),
            subjects=subject_totals,
            tasks_total=tasks_total,
            tasks_completed=tasks_completed,
            planned_minutes=planned_minutes,
            current_streak_days=streak,
        )

    async def weekly_summary(
        self,
        *,
        user_id: uuid.UUID,
        anchor_day: date,
        tz: ZoneInfo,
        daily_goal_minutes: int,
        weekly_goal_minutes: int,
        scheduled_days_mask: int,
    ) -> WeeklySummary:
        first_day, last_day = week_bounds(anchor_day)
        window = range_window(first_day, last_day, tz)
        sessions = await self._sessions_between(user_id, window.start, window.end)
        subjects = await self._subject_lookup(user_id)

        by_day: dict[date, list[StudySession]] = defaultdict(list)
        for session in sessions:
            by_day[local_date_of(ensure_utc(session.started_at), tz)].append(session)

        day_totals: list[DayTotals] = []
        for day in days_in_range(first_day, last_day):
            day_sessions = by_day.get(day, [])
            verified, manual, excluded = _split_seconds(day_sessions)
            day_totals.append(
                DayTotals(
                    day=day,
                    verified_seconds=verified,
                    manual_seconds=manual,
                    excluded_seconds=excluded,
                    session_count=len(day_sessions),
                    is_scheduled=is_scheduled_day(day, scheduled_days_mask),
                    goal_minutes=daily_goal_minutes,
                )
            )

        verified, manual, excluded = _split_seconds(sessions)
        scheduled = [totals for totals in day_totals if totals.is_scheduled]
        counted = [s for s in sessions if s.duration_seconds > 0]
        average = int(sum(s.duration_seconds for s in counted) / len(counted)) if counted else 0

        return WeeklySummary(
            week_start=first_day,
            week_end=last_day,
            timezone=str(tz),
            verified_seconds=verified,
            manual_seconds=manual,
            excluded_seconds=excluded,
            goal_minutes=weekly_goal_minutes,
            days=day_totals,
            subjects=_subject_totals(sessions, subjects),
            scheduled_days=len(scheduled),
            scheduled_days_met=sum(1 for totals in scheduled if totals.goal_met),
            average_session_seconds=average,
            session_count=len(sessions),
        )

    async def yearly_insights(
        self,
        *,
        user_id: uuid.UUID,
        year: int,
        tz: ZoneInfo,
        daily_goal_minutes: int,
    ) -> YearlyInsights:
        """A year seen at a glance: a per-day heatmap, monthly totals, and the shape of it.

        Everything is bucketed into user-local days in Python (ADR-0003), so a session at
        23:30 in Seoul lands on the Seoul day even though the row is stored in UTC.
        """
        first_day = date(year, 1, 1)
        last_day = date(year, 12, 31)
        window = range_window(first_day, last_day, tz)
        sessions = await self._sessions_between(user_id, window.start, window.end)
        subjects = await self._subject_lookup(user_id)

        verified_by_day: dict[date, int] = defaultdict(int)
        sessions_by_day: dict[date, int] = defaultdict(int)
        for session in sessions:
            local_day = local_date_of(ensure_utc(session.started_at), tz)
            sessions_by_day[local_day] += 1
            if _is_verified(session):
                verified_by_day[local_day] += session.duration_seconds

        goal_seconds = daily_goal_minutes * 60
        heatmap = [
            HeatmapDay(
                day=day,
                verified_seconds=verified_by_day.get(day, 0),
                goal_met=goal_seconds > 0 and verified_by_day.get(day, 0) >= goal_seconds,
            )
            for day in days_in_range(first_day, last_day)
        ]

        months: list[MonthTotals] = []
        for month in range(1, 13):
            days = [d for d in verified_by_day if d.year == year and d.month == month]
            month_days = [d for d in days_in_range(first_day, last_day) if d.month == month]
            months.append(
                MonthTotals(
                    month=f"{year:04d}-{month:02d}",
                    verified_seconds=sum(verified_by_day.get(d, 0) for d in month_days),
                    session_count=sum(sessions_by_day.get(d, 0) for d in month_days),
                    active_days=sum(1 for d in days if verified_by_day.get(d, 0) > 0),
                )
            )

        verified, manual, _ = _split_seconds(sessions)
        active = [day for day, seconds in verified_by_day.items() if seconds > 0]
        busiest = max(active, key=lambda d: verified_by_day[d]) if active else None

        return YearlyInsights(
            year=year,
            timezone=str(tz),
            verified_seconds=verified,
            manual_seconds=manual,
            session_count=len(sessions),
            active_days=len(active),
            longest_streak_days=_longest_run(sorted(active)),
            busiest_day=busiest,
            months=months,
            heatmap=heatmap,
            subjects=_subject_totals(sessions, subjects),
        )

    async def current_streak(
        self,
        *,
        user_id: uuid.UUID,
        today: date,
        tz: ZoneInfo,
        goal_minutes: int,
        scheduled_days_mask: int,
        lookback_days: int = 120,
    ) -> int:
        """Consecutive scheduled days meeting the daily goal, counting back from today.

        Non-scheduled days are skipped rather than breaking the streak: a rest day the user
        planned is not a failure. Today is only allowed to *extend* a streak, never to end
        one, so the number does not drop to zero every morning.
        """
        if goal_minutes <= 0:
            return 0

        first_day = today - timedelta(days=lookback_days)
        window = range_window(first_day, today, tz)
        sessions = await self._sessions_between(user_id, window.start, window.end)

        verified_by_day: dict[date, int] = defaultdict(int)
        for session in sessions:
            if _is_verified(session):
                verified_by_day[local_date_of(ensure_utc(session.started_at), tz)] += (
                    session.duration_seconds
                )

        goal_seconds = goal_minutes * 60
        streak = 0
        cursor = today
        while cursor >= first_day:
            if is_scheduled_day(cursor, scheduled_days_mask):
                if verified_by_day.get(cursor, 0) >= goal_seconds:
                    streak += 1
                elif cursor == today:
                    pass  # Today is still in progress.
                else:
                    break
            cursor -= timedelta(days=1)
        return streak

    async def _task_totals(self, user_id: uuid.UUID, day: date) -> tuple[int, int, int]:
        result = await self._db.execute(
            select(Task)
            .join(DailyPlan, Task.plan_id == DailyPlan.id)
            .where(DailyPlan.user_id == user_id, DailyPlan.plan_date == day)
        )
        tasks = list(result.scalars().all())
        completed = sum(1 for task in tasks if task.status == TaskStatus.DONE.value)
        planned = sum(task.estimated_minutes for task in tasks)
        return len(tasks), completed, planned


def _longest_run(days: list[date]) -> int:
    """Longest run of consecutive calendar days in a sorted, de-duplicated list."""
    longest = current = 0
    previous: date | None = None
    for day in days:
        if previous is not None and (day - previous).days == 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous = day
    return longest


def _is_verified(session: StudySession) -> bool:
    """Timer-produced time that passed integrity checks."""
    return (
        session.source == SessionSource.TIMER.value
        and session.integrity_status == IntegrityStatus.OK.value
    )


def _split_seconds(sessions: list[StudySession]) -> tuple[int, int, int]:
    """Partition session time into (verified, manual, excluded-from-competition)."""
    verified = manual = excluded = 0
    for session in sessions:
        if session.source == SessionSource.MANUAL.value:
            manual += session.duration_seconds
        elif session.integrity_status == IntegrityStatus.OK.value:
            verified += session.duration_seconds
        else:
            excluded += session.duration_seconds
    return verified, manual, excluded


def _subject_totals(
    sessions: list[StudySession], subjects: dict[uuid.UUID, Subject]
) -> list[SubjectTotal]:
    verified: dict[uuid.UUID, int] = defaultdict(int)
    manual: dict[uuid.UUID, int] = defaultdict(int)

    for session in sessions:
        if session.source == SessionSource.MANUAL.value:
            manual[session.subject_id] += session.duration_seconds
        elif session.integrity_status == IntegrityStatus.OK.value:
            verified[session.subject_id] += session.duration_seconds

    totals: list[SubjectTotal] = []
    for subject_id in set(verified) | set(manual):
        subject = subjects.get(subject_id)
        if subject is None:
            continue
        totals.append(
            SubjectTotal(
                subject_id=subject_id,
                name=subject.name,
                color_hex=subject.color_hex,
                verified_seconds=verified.get(subject_id, 0),
                manual_seconds=manual.get(subject_id, 0),
            )
        )
    totals.sort(key=lambda item: (-item.total_seconds, item.name))
    return totals
