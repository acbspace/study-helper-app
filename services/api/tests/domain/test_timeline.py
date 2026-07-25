"""Timeline derivation: the single definition of elapsed study time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError, UnprocessableError
from app.domain.sessions.timeline import TimelineEvent, derive_timeline, validate_transition
from app.models.enums import SessionEventType, SessionStatus

START = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)


def event(sequence: int, kind: SessionEventType, offset_minutes: float) -> TimelineEvent:
    return TimelineEvent(
        sequence=sequence,
        event_type=kind,
        occurred_at=START + timedelta(minutes=offset_minutes),
    )


class TestElapsedCalculation:
    def test_running_session_counts_up_to_now(self) -> None:
        result = derive_timeline(
            [event(1, SessionEventType.START, 0)], now=START + timedelta(minutes=30)
        )
        assert result.status is SessionStatus.ACTIVE
        assert result.elapsed_seconds == 30 * 60

    def test_pause_stops_the_clock(self) -> None:
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.PAUSE, 25),
        ]
        # An hour passes while paused; elapsed must not move.
        result = derive_timeline(events, now=START + timedelta(minutes=85))
        assert result.status is SessionStatus.PAUSED
        assert result.elapsed_seconds == 25 * 60

    def test_resume_restarts_the_clock(self) -> None:
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.PAUSE, 25),
            event(3, SessionEventType.RESUME, 40),
        ]
        result = derive_timeline(events, now=START + timedelta(minutes=50))
        # 25 minutes before the pause + 10 minutes since resuming.
        assert result.elapsed_seconds == 35 * 60
        assert result.status is SessionStatus.ACTIVE

    def test_stop_finalises_duration(self) -> None:
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.PAUSE, 25),
            event(3, SessionEventType.RESUME, 40),
            event(4, SessionEventType.STOP, 60),
        ]
        # `now` is far in the future: a stopped session must ignore it entirely.
        result = derive_timeline(events, now=START + timedelta(days=3))
        assert result.status is SessionStatus.COMPLETED
        assert result.elapsed_seconds == 45 * 60
        assert result.ended_at == START + timedelta(minutes=60)
        assert result.interval_count == 2

    def test_multiple_pause_cycles_accumulate(self) -> None:
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.PAUSE, 20),
            event(3, SessionEventType.RESUME, 30),
            event(4, SessionEventType.PAUSE, 50),
            event(5, SessionEventType.RESUME, 55),
            event(6, SessionEventType.STOP, 70),
        ]
        result = derive_timeline(events, now=START + timedelta(hours=2))
        assert result.elapsed_seconds == (20 + 20 + 15) * 60
        assert result.interval_count == 3
        assert result.longest_interval_seconds == 20 * 60

    def test_events_are_ordered_by_sequence_not_arrival(self) -> None:
        """Offline sync may deliver events out of order; sequence is authoritative."""
        events = [
            event(4, SessionEventType.STOP, 60),
            event(1, SessionEventType.START, 0),
            event(3, SessionEventType.RESUME, 40),
            event(2, SessionEventType.PAUSE, 25),
        ]
        result = derive_timeline(events, now=START + timedelta(hours=5))
        assert result.elapsed_seconds == 45 * 60
        assert result.status is SessionStatus.COMPLETED


class TestInvalidTimelines:
    def test_empty_stream_is_rejected(self) -> None:
        with pytest.raises(UnprocessableError):
            derive_timeline([], now=START)

    def test_strict_mode_raises_on_impossible_sequence(self) -> None:
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.RESUME, 10),  # resume while already running
        ]
        with pytest.raises(UnprocessableError) as exc_info:
            derive_timeline(events, now=START + timedelta(minutes=20))
        assert "duplicate_resume" in exc_info.value.details["problems"]

    def test_lenient_mode_reports_problems_instead_of_raising(self) -> None:
        """Sync must never throw away a user's study time over a malformed stream — it
        stores the session and flags it instead."""
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.RESUME, 10),
        ]
        result = derive_timeline(events, now=START + timedelta(minutes=20), strict=False)
        assert "duplicate_resume" in result.problems
        assert result.elapsed_seconds > 0

    def test_non_monotonic_timestamps_are_flagged_and_clamped(self) -> None:
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.STOP, -10),  # ends before it began
        ]
        result = derive_timeline(events, now=START, strict=False)
        assert "non_monotonic_timestamps" in result.problems
        assert result.elapsed_seconds == 0

    def test_missing_start_event_is_flagged(self) -> None:
        result = derive_timeline(
            [event(1, SessionEventType.PAUSE, 5)], now=START + timedelta(minutes=10), strict=False
        )
        assert "missing_start_event" in result.problems

    def test_events_after_stop_are_flagged(self) -> None:
        events = [
            event(1, SessionEventType.START, 0),
            event(2, SessionEventType.STOP, 30),
            event(3, SessionEventType.RESUME, 40),
        ]
        result = derive_timeline(events, now=START + timedelta(hours=1), strict=False)
        assert "events_after_stop" in result.problems
        assert result.elapsed_seconds == 30 * 60


class TestTransitionRules:
    @pytest.mark.parametrize(
        ("status", "event_type"),
        [
            (SessionStatus.ACTIVE, SessionEventType.PAUSE),
            (SessionStatus.ACTIVE, SessionEventType.STOP),
            (SessionStatus.PAUSED, SessionEventType.RESUME),
            (SessionStatus.PAUSED, SessionEventType.STOP),
        ],
    )
    def test_allowed_transitions(self, status: SessionStatus, event_type: SessionEventType) -> None:
        validate_transition(status, event_type)

    @pytest.mark.parametrize(
        ("status", "event_type"),
        [
            (SessionStatus.ACTIVE, SessionEventType.RESUME),
            (SessionStatus.PAUSED, SessionEventType.PAUSE),
            (SessionStatus.COMPLETED, SessionEventType.STOP),
            (SessionStatus.COMPLETED, SessionEventType.RESUME),
            (SessionStatus.DISCARDED, SessionEventType.PAUSE),
        ],
    )
    def test_rejected_transitions(
        self, status: SessionStatus, event_type: SessionEventType
    ) -> None:
        with pytest.raises(AppError) as exc_info:
            validate_transition(status, event_type)
        assert exc_info.value.code.value == "invalid_transition"


def test_naive_timestamps_are_treated_as_utc() -> None:
    """SQLite returns naive datetimes; they must not be mistaken for local time."""
    naive_start = datetime(2026, 7, 22, 9, 0)
    events = [
        TimelineEvent(1, SessionEventType.START, naive_start),
        TimelineEvent(2, SessionEventType.STOP, naive_start + timedelta(minutes=45)),
    ]
    result = derive_timeline(events, now=START + timedelta(hours=3))
    assert result.elapsed_seconds == 45 * 60
