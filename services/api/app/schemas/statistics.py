"""Statistics contracts.

Every aggregate names the time zone it was computed in — a total without a zone is
ambiguous and clients should never have to guess.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.schemas.common import ResponseModel


class SubjectTotalResponse(ResponseModel):
    subject_id: uuid.UUID
    name: str
    color_hex: str
    verified_seconds: int
    manual_seconds: int
    total_seconds: int


class DayTotalsResponse(ResponseModel):
    day: date
    verified_seconds: int
    manual_seconds: int
    excluded_seconds: int
    total_seconds: int
    session_count: int
    is_scheduled: bool
    goal_met: bool


class DailySummaryResponse(ResponseModel):
    date: date
    timezone: str
    verified_seconds: int
    manual_seconds: int
    excluded_seconds: int
    total_seconds: int
    goal_minutes: int
    goal_progress: float
    session_count: int
    current_streak_days: int
    tasks_total: int
    tasks_completed: int
    planned_minutes: int
    subjects: list[SubjectTotalResponse]


class WeeklySummaryResponse(ResponseModel):
    week_start: date
    week_end: date
    timezone: str
    verified_seconds: int
    manual_seconds: int
    excluded_seconds: int
    total_seconds: int
    goal_minutes: int
    scheduled_days: int
    scheduled_days_met: int
    goal_completion_rate: float
    average_session_seconds: int
    session_count: int
    days: list[DayTotalsResponse]
    subjects: list[SubjectTotalResponse]


class StatisticsSummaryResponse(ResponseModel):
    """What the Today screen needs in a single round trip."""

    today: DailySummaryResponse
    week: WeeklySummaryResponse


class HeatmapDayResponse(ResponseModel):
    day: date
    verified_seconds: int
    goal_met: bool


class MonthTotalsResponse(ResponseModel):
    month: str
    verified_seconds: int
    session_count: int
    active_days: int


class YearlyInsightsResponse(ResponseModel):
    year: int
    timezone: str
    verified_seconds: int
    manual_seconds: int
    total_seconds: int
    session_count: int
    active_days: int
    longest_streak_days: int
    busiest_day: date | None = None
    months: list[MonthTotalsResponse]
    heatmap: list[HeatmapDayResponse]
    subjects: list[SubjectTotalResponse]
