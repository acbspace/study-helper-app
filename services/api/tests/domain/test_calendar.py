"""User-local calendar arithmetic, including DST correctness."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.domain.statistics.calendar import (
    day_window,
    is_scheduled_day,
    local_date_of,
    range_window,
    resolve_timezone,
    scheduled_days_in_range,
    week_bounds,
)

SEOUL = ZoneInfo("Asia/Seoul")  # UTC+9, no DST
NEW_YORK = ZoneInfo("America/New_York")  # DST transitions


class TestLocalDate:
    def test_late_evening_in_seoul_belongs_to_that_local_day(self) -> None:
        """23:30 Seoul on the 22nd is 14:30 UTC on the 22nd — same date here."""
        moment = datetime(2026, 7, 22, 14, 30, tzinfo=UTC)
        assert local_date_of(moment, SEOUL) == date(2026, 7, 22)

    def test_utc_evening_can_be_the_next_day_in_seoul(self) -> None:
        """22:00 UTC on the 22nd is 07:00 Seoul on the 23rd."""
        moment = datetime(2026, 7, 22, 22, 0, tzinfo=UTC)
        assert local_date_of(moment, SEOUL) == date(2026, 7, 23)

    def test_utc_morning_is_still_the_previous_day_in_new_york(self) -> None:
        moment = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)
        assert local_date_of(moment, NEW_YORK) == date(2026, 7, 21)

    def test_naive_datetimes_are_treated_as_utc(self) -> None:
        assert local_date_of(datetime(2026, 7, 22, 22, 0), SEOUL) == date(2026, 7, 23)


class TestWindows:
    def test_day_window_covers_exactly_24_hours_in_a_fixed_offset_zone(self) -> None:
        window = day_window(date(2026, 7, 22), SEOUL)
        assert window.start == datetime(2026, 7, 21, 15, 0, tzinfo=UTC)
        assert window.end == datetime(2026, 7, 22, 15, 0, tzinfo=UTC)

    def test_spring_forward_day_is_23_hours(self) -> None:
        """DST is why windows are built from midnight-to-midnight, not 23:59:59."""
        window = day_window(date(2026, 3, 8), NEW_YORK)  # US spring forward
        assert (window.end - window.start).total_seconds() == 23 * 3600

    def test_fall_back_day_is_25_hours(self) -> None:
        window = day_window(date(2026, 11, 1), NEW_YORK)
        assert (window.end - window.start).total_seconds() == 25 * 3600

    def test_window_is_half_open(self) -> None:
        window = day_window(date(2026, 7, 22), SEOUL)
        assert window.contains(window.start)
        assert not window.contains(window.end)

    def test_range_window_spans_inclusive_local_days(self) -> None:
        window = range_window(date(2026, 7, 20), date(2026, 7, 26), SEOUL)
        assert (window.end - window.start).days == 7


class TestWeeks:
    def test_weeks_start_on_monday(self) -> None:
        start, end = week_bounds(date(2026, 7, 22))  # a Wednesday
        assert start == date(2026, 7, 20)
        assert end == date(2026, 7, 26)
        assert start.weekday() == 0

    def test_sunday_belongs_to_the_week_that_started_monday(self) -> None:
        start, end = week_bounds(date(2026, 7, 26))
        assert start == date(2026, 7, 20)
        assert end == date(2026, 7, 26)


class TestScheduledDays:
    def test_weekday_mask_matches_monday_through_friday(self) -> None:
        mask = 0b0011111
        assert is_scheduled_day(date(2026, 7, 20), mask)  # Monday
        assert is_scheduled_day(date(2026, 7, 24), mask)  # Friday
        assert not is_scheduled_day(date(2026, 7, 25), mask)  # Saturday
        assert not is_scheduled_day(date(2026, 7, 26), mask)  # Sunday

    def test_weekend_only_schedule(self) -> None:
        mask = 0b1100000
        assert not is_scheduled_day(date(2026, 7, 20), mask)
        assert is_scheduled_day(date(2026, 7, 25), mask)
        assert is_scheduled_day(date(2026, 7, 26), mask)

    def test_scheduled_days_in_range_filters_correctly(self) -> None:
        days = scheduled_days_in_range(date(2026, 7, 20), date(2026, 7, 26), 0b0011111)
        assert len(days) == 5
        assert all(d.weekday() < 5 for d in days)

    def test_empty_mask_yields_no_scheduled_days(self) -> None:
        assert scheduled_days_in_range(date(2026, 7, 20), date(2026, 7, 26), 0) == []


class TestTimezoneResolution:
    def test_known_zone_resolves(self) -> None:
        assert str(resolve_timezone("Asia/Seoul")) == "Asia/Seoul"

    def test_unknown_zone_falls_back_to_utc_rather_than_crashing(self) -> None:
        """A stale zone name must never break a user's statistics."""
        assert str(resolve_timezone("Mars/Olympus_Mons")) == "UTC"
        assert str(resolve_timezone("")) == "UTC"
