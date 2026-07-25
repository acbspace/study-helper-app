"""Pure derivation of session state from an event stream.

This module is the single definition of "how long did they study": both the live endpoints
and offline sync run their events through it, so there is exactly one answer. It has no
I/O, no clock access, and no database types — everything it needs arrives as arguments,
which is what makes the competitive scoring reproducible and testable.

Elapsed time is the sum of [start|resume → pause|stop] intervals. A still-running session
counts the open interval up to `now`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.clock import ensure_utc
from app.core.errors import AppError, ErrorCode, UnprocessableError
from app.models.enums import SessionEventType, SessionStatus


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """An event as the domain sees it — decoupled from the ORM row."""

    sequence: int
    event_type: SessionEventType
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineResult:
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None
    elapsed_seconds: int
    # Number of [start|resume → pause|stop] intervals; a proxy for focus blocks.
    interval_count: int
    longest_interval_seconds: int
    problems: tuple[str, ...] = field(default=())


_OPENING = frozenset({SessionEventType.START, SessionEventType.RESUME})
_CLOSING = frozenset({SessionEventType.PAUSE, SessionEventType.STOP})


def derive_timeline(
    events: list[TimelineEvent], *, now: datetime, strict: bool = True
) -> TimelineResult:
    """Fold an event stream into session state.

    Args:
        events: All known events for one session, in any order (sorted internally).
        now: Reference time used to measure a still-open interval.
        strict: Raise on an impossible stream. When False, problems are reported in the
            result instead — the sync path uses this to store and flag a bad stream rather
            than reject the user's study time outright.

    Raises:
        UnprocessableError: When `strict` and the stream cannot describe a real session.
    """
    if not events:
        raise UnprocessableError(ErrorCode.TIMELINE_INVALID, "A session needs at least one event.")

    ordered = sorted(events, key=lambda event: (event.sequence, event.occurred_at))
    problems: list[str] = []

    first = ordered[0]
    if first.event_type is not SessionEventType.START:
        problems.append("missing_start_event")

    started_at = ensure_utc(first.occurred_at)
    now_utc = ensure_utc(now)

    elapsed = 0.0
    longest = 0.0
    intervals = 0
    open_since: datetime | None = None
    ended_at: datetime | None = None
    previous_at = started_at
    stopped = False

    for event in ordered:
        occurred_at = ensure_utc(event.occurred_at)

        if occurred_at < previous_at:
            problems.append("non_monotonic_timestamps")
            occurred_at = previous_at
        previous_at = occurred_at

        if stopped:
            problems.append("events_after_stop")
            continue

        if event.event_type in _OPENING:
            if open_since is not None:
                # start-after-start / resume-while-running: ignore, keep the earlier open.
                problems.append(f"duplicate_{event.event_type.value}")
                continue
            open_since = occurred_at
        elif event.event_type in _CLOSING:
            if open_since is None:
                problems.append(f"unexpected_{event.event_type.value}")
            else:
                span = (occurred_at - open_since).total_seconds()
                elapsed += span
                longest = max(longest, span)
                intervals += 1
                open_since = None
            if event.event_type is SessionEventType.STOP:
                stopped = True
                ended_at = occurred_at

    if stopped:
        status = SessionStatus.COMPLETED
    elif open_since is not None:
        status = SessionStatus.ACTIVE
        # The open interval counts up to `now` but never runs backwards.
        span = max((now_utc - open_since).total_seconds(), 0.0)
        elapsed += span
        longest = max(longest, span)
    else:
        status = SessionStatus.PAUSED

    if problems and strict:
        raise UnprocessableError(
            ErrorCode.TIMELINE_INVALID,
            "The session's event history is inconsistent.",
            problems=sorted(set(problems)),
        )

    return TimelineResult(
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        elapsed_seconds=int(elapsed),
        interval_count=intervals,
        longest_interval_seconds=int(longest),
        problems=tuple(sorted(set(problems))),
    )


def validate_transition(current: SessionStatus, event_type: SessionEventType) -> None:
    """Guard a live state change before any event is written.

    Raises:
        UnprocessableError: When the transition is not legal from `current`.
    """
    allowed: dict[SessionStatus, frozenset[SessionEventType]] = {
        SessionStatus.ACTIVE: frozenset({SessionEventType.PAUSE, SessionEventType.STOP}),
        SessionStatus.PAUSED: frozenset({SessionEventType.RESUME, SessionEventType.STOP}),
        SessionStatus.COMPLETED: frozenset(),
        SessionStatus.DISCARDED: frozenset(),
    }
    if event_type not in allowed[current]:
        raise AppError(
            ErrorCode.INVALID_TRANSITION,
            f"Cannot {event_type.value} a session that is {current.value}.",
            status_code=400,
            details={"current_status": current.value, "attempted": event_type.value},
        )
