"""Time access.

Domain functions receive `now` explicitly so they stay deterministic and testable; only
the edges (routers, jobs) read the wall clock through this module.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalise a datetime to UTC, treating naive values as already-UTC.

    Naive values arrive from SQLite (which does not preserve tzinfo) and from clients that
    serialise without an offset; both are stored as UTC by convention.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
