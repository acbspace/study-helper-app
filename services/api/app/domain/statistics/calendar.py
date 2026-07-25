"""User-local calendar arithmetic.

Every "day" and "week" in this product is the user's, not the server's. A session that
starts at 23:30 in Seoul belongs to that Seoul day even though it is 14:30 UTC. These
helpers convert between the user's local calendar and the UTC windows the database stores,
and they are the only place that conversion is allowed to happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_timezone(name: str) -> ZoneInfo:
    """Return the IANA zone, falling back to UTC for unknown names.

    A stale or misspelled zone must not break a user's statistics; UTC is the safe,
    explicit default.
    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


@dataclass(frozen=True, slots=True)
class UtcWindow:
    """A half-open [start, end) window in UTC covering a local date range."""

    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


def local_date_of(moment: datetime, tz: ZoneInfo) -> date:
    """The user-local calendar date a UTC instant falls on."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz).date()


def day_window(day: date, tz: ZoneInfo) -> UtcWindow:
    """UTC window covering one local day.

    Uses "start of next day" rather than 23:59:59 so DST transitions (a 23- or 25-hour
    day) stay exact.
    """
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return UtcWindow(start_local.astimezone(UTC), end_local.astimezone(UTC))


def range_window(first_day: date, last_day: date, tz: ZoneInfo) -> UtcWindow:
    """UTC window covering an inclusive range of local days."""
    start_local = datetime.combine(first_day, time.min, tzinfo=tz)
    end_local = datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=tz)
    return UtcWindow(start_local.astimezone(UTC), end_local.astimezone(UTC))


def week_start(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())


def week_bounds(day: date) -> tuple[date, date]:
    """Monday and Sunday of the ISO week containing `day`."""
    start = week_start(day)
    return start, start + timedelta(days=6)


def days_in_range(first_day: date, last_day: date) -> list[date]:
    span = (last_day - first_day).days
    return [first_day + timedelta(days=offset) for offset in range(span + 1)]


def is_scheduled_day(day: date, scheduled_days_mask: int) -> bool:
    """Whether the user planned to study on this weekday.

    Bitmask: Monday = 1 << 0 … Sunday = 1 << 6. Rest days the user chose are never
    penalised by the league (see ADR-0006).
    """
    return bool(scheduled_days_mask & (1 << day.weekday()))


def scheduled_days_in_range(
    first_day: date, last_day: date, scheduled_days_mask: int
) -> list[date]:
    return [
        day
        for day in days_in_range(first_day, last_day)
        if is_scheduled_day(day, scheduled_days_mask)
    ]
