"""Statistics routes. Dates are always interpreted in the caller's time zone."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, StatisticsServiceDep, UserTimezone
from app.core.clock import utc_now
from app.domain.statistics.calendar import local_date_of
from app.domain.statistics.service import DailySummary, WeeklySummary, YearlyInsights
from app.schemas.statistics import (
    DailySummaryResponse,
    DayTotalsResponse,
    HeatmapDayResponse,
    MonthTotalsResponse,
    StatisticsSummaryResponse,
    SubjectTotalResponse,
    WeeklySummaryResponse,
    YearlyInsightsResponse,
)

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("/summary", response_model=StatisticsSummaryResponse, summary="Today + this week")
async def summary(
    user: CurrentUser,
    statistics: StatisticsServiceDep,
    tz: UserTimezone,
    on_date: date | None = Query(default=None, alias="date"),
) -> StatisticsSummaryResponse:
    """Everything the Today screen needs in one round trip."""
    settings = user.settings
    day = on_date or local_date_of(utc_now(), tz)

    daily = await statistics.daily_summary(
        user_id=user.id,
        day=day,
        tz=tz,
        goal_minutes=settings.daily_goal_minutes,
        scheduled_days_mask=settings.scheduled_study_days,
    )
    weekly = await statistics.weekly_summary(
        user_id=user.id,
        anchor_day=day,
        tz=tz,
        daily_goal_minutes=settings.daily_goal_minutes,
        weekly_goal_minutes=settings.weekly_goal_minutes,
        scheduled_days_mask=settings.scheduled_study_days,
    )
    return StatisticsSummaryResponse(today=_daily_response(daily), week=_weekly_response(weekly))


@router.get("/daily", response_model=DailySummaryResponse, summary="One day")
async def daily(
    user: CurrentUser,
    statistics: StatisticsServiceDep,
    tz: UserTimezone,
    on_date: date | None = Query(default=None, alias="date"),
) -> DailySummaryResponse:
    day = on_date or local_date_of(utc_now(), tz)
    result = await statistics.daily_summary(
        user_id=user.id,
        day=day,
        tz=tz,
        goal_minutes=user.settings.daily_goal_minutes,
        scheduled_days_mask=user.settings.scheduled_study_days,
    )
    return _daily_response(result)


@router.get("/weekly", response_model=WeeklySummaryResponse, summary="One ISO week")
async def weekly(
    user: CurrentUser,
    statistics: StatisticsServiceDep,
    tz: UserTimezone,
    on_date: date | None = Query(default=None, alias="date"),
) -> WeeklySummaryResponse:
    day = on_date or local_date_of(utc_now(), tz)
    result = await statistics.weekly_summary(
        user_id=user.id,
        anchor_day=day,
        tz=tz,
        daily_goal_minutes=user.settings.daily_goal_minutes,
        weekly_goal_minutes=user.settings.weekly_goal_minutes,
        scheduled_days_mask=user.settings.scheduled_study_days,
    )
    return _weekly_response(result)


@router.get("/yearly", response_model=YearlyInsightsResponse, summary="A year at a glance")
async def yearly(
    user: CurrentUser,
    statistics: StatisticsServiceDep,
    tz: UserTimezone,
    year: int | None = Query(default=None, ge=2000, le=2100),
) -> YearlyInsightsResponse:
    """The calendar heatmap, monthly totals, and headline numbers for a whole year."""
    resolved_year = year or local_date_of(utc_now(), tz).year
    insights = await statistics.yearly_insights(
        user_id=user.id,
        year=resolved_year,
        tz=tz,
        daily_goal_minutes=user.settings.daily_goal_minutes,
    )
    return _yearly_response(insights)


def _yearly_response(insights: YearlyInsights) -> YearlyInsightsResponse:
    return YearlyInsightsResponse(
        year=insights.year,
        timezone=insights.timezone,
        verified_seconds=insights.verified_seconds,
        manual_seconds=insights.manual_seconds,
        total_seconds=insights.total_seconds,
        session_count=insights.session_count,
        active_days=insights.active_days,
        longest_streak_days=insights.longest_streak_days,
        busiest_day=insights.busiest_day,
        months=[
            MonthTotalsResponse(
                month=month.month,
                verified_seconds=month.verified_seconds,
                session_count=month.session_count,
                active_days=month.active_days,
            )
            for month in insights.months
        ],
        heatmap=[
            HeatmapDayResponse(
                day=day.day, verified_seconds=day.verified_seconds, goal_met=day.goal_met
            )
            for day in insights.heatmap
        ],
        subjects=_subject_responses(insights.subjects),
    )


def _subject_responses(summary_subjects: list) -> list[SubjectTotalResponse]:  # type: ignore[type-arg]
    return [
        SubjectTotalResponse(
            subject_id=item.subject_id,
            name=item.name,
            color_hex=item.color_hex,
            verified_seconds=item.verified_seconds,
            manual_seconds=item.manual_seconds,
            total_seconds=item.total_seconds,
        )
        for item in summary_subjects
    ]


def _daily_response(summary: DailySummary) -> DailySummaryResponse:
    return DailySummaryResponse(
        date=summary.day,
        timezone=summary.timezone,
        verified_seconds=summary.verified_seconds,
        manual_seconds=summary.manual_seconds,
        excluded_seconds=summary.excluded_seconds,
        total_seconds=summary.total_seconds,
        goal_minutes=summary.goal_minutes,
        goal_progress=summary.goal_progress,
        session_count=summary.session_count,
        current_streak_days=summary.current_streak_days,
        tasks_total=summary.tasks_total,
        tasks_completed=summary.tasks_completed,
        planned_minutes=summary.planned_minutes,
        subjects=_subject_responses(summary.subjects),
    )


def _weekly_response(summary: WeeklySummary) -> WeeklySummaryResponse:
    return WeeklySummaryResponse(
        week_start=summary.week_start,
        week_end=summary.week_end,
        timezone=summary.timezone,
        verified_seconds=summary.verified_seconds,
        manual_seconds=summary.manual_seconds,
        excluded_seconds=summary.excluded_seconds,
        total_seconds=summary.total_seconds,
        goal_minutes=summary.goal_minutes,
        scheduled_days=summary.scheduled_days,
        scheduled_days_met=summary.scheduled_days_met,
        goal_completion_rate=summary.goal_completion_rate,
        average_session_seconds=summary.average_session_seconds,
        session_count=summary.session_count,
        days=[
            DayTotalsResponse(
                day=day.day,
                verified_seconds=day.verified_seconds,
                manual_seconds=day.manual_seconds,
                excluded_seconds=day.excluded_seconds,
                total_seconds=day.total_seconds,
                session_count=day.session_count,
                is_scheduled=day.is_scheduled,
                goal_met=day.goal_met,
            )
            for day in summary.days
        ],
        subjects=_subject_responses(summary.subjects),
    )
