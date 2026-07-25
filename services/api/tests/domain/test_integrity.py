"""Anti-cheat rules: flag, never delete; explain, never guess."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.sessions.integrity import (
    IntegrityReason,
    IntegrityThresholds,
    SessionIntegrityInput,
    evaluate_session,
)
from app.models.enums import IntegrityStatus, SessionSource

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
THRESHOLDS = IntegrityThresholds()


def make_input(**overrides: object) -> SessionIntegrityInput:
    defaults: dict[str, object] = {
        "source": SessionSource.TIMER,
        "started_at": NOW - timedelta(hours=1),
        "ended_at": NOW,
        "elapsed_seconds": 3600,
        "longest_interval_seconds": 3600,
        "server_received_at": NOW,
    }
    defaults.update(overrides)
    return SessionIntegrityInput(**defaults)  # type: ignore[arg-type]


class TestNormalSessions:
    def test_an_ordinary_session_passes(self) -> None:
        verdict = evaluate_session(make_input(), THRESHOLDS)
        assert verdict.status is IntegrityStatus.OK
        assert verdict.counts_for_league

    def test_a_session_synced_hours_late_is_still_fine(self) -> None:
        """Late arrival is what offline support is for — it is not suspicious."""
        verdict = evaluate_session(
            make_input(
                started_at=NOW - timedelta(hours=6),
                ended_at=NOW - timedelta(hours=5),
                server_received_at=NOW,
            ),
            THRESHOLDS,
        )
        assert verdict.status is IntegrityStatus.OK


class TestManualTime:
    def test_manual_entries_are_excluded_not_flagged(self) -> None:
        """The user did nothing wrong; the time simply cannot be verified."""
        verdict = evaluate_session(make_input(source=SessionSource.MANUAL), THRESHOLDS)
        assert verdict.status is IntegrityStatus.EXCLUDED
        assert verdict.reasons == (IntegrityReason.MANUAL_ENTRY,)
        assert not verdict.counts_for_league

    def test_manual_entries_get_a_plain_language_explanation(self) -> None:
        verdict = evaluate_session(make_input(source=SessionSource.MANUAL), THRESHOLDS)
        message = verdict.messages()[0]
        assert "personal statistics" in message
        assert "League Points" in message


class TestSuspiciousSessions:
    def test_marathon_sessions_are_flagged(self) -> None:
        verdict = evaluate_session(
            make_input(elapsed_seconds=13 * 3600, longest_interval_seconds=3600), THRESHOLDS
        )
        assert verdict.status is IntegrityStatus.FLAGGED
        assert IntegrityReason.MARATHON_SESSION in verdict.reasons

    def test_unbroken_intervals_beyond_the_limit_are_flagged(self) -> None:
        verdict = evaluate_session(
            make_input(elapsed_seconds=7 * 3600, longest_interval_seconds=7 * 3600), THRESHOLDS
        )
        assert IntegrityReason.LONG_SINGLE_INTERVAL in verdict.reasons

    def test_overlapping_sessions_are_flagged(self) -> None:
        verdict = evaluate_session(make_input(overlaps_existing=True), THRESHOLDS)
        assert IntegrityReason.OVERLAPPING_SESSION in verdict.reasons

    def test_broken_timelines_are_flagged(self) -> None:
        verdict = evaluate_session(
            make_input(timeline_problems=("non_monotonic_timestamps",)), THRESHOLDS
        )
        assert IntegrityReason.TIMELINE_INVALID in verdict.reasons

    def test_future_dated_events_are_flagged_as_clock_skew(self) -> None:
        verdict = evaluate_session(
            make_input(latest_event_at=NOW + timedelta(hours=2), server_received_at=NOW),
            THRESHOLDS,
        )
        assert IntegrityReason.CLOCK_SKEW in verdict.reasons

    def test_late_retroactive_edits_are_flagged(self) -> None:
        verdict = evaluate_session(
            make_input(
                started_at=NOW - timedelta(days=5),
                ended_at=NOW - timedelta(days=5) + timedelta(hours=1),
                server_received_at=NOW,
            ),
            THRESHOLDS,
        )
        assert IntegrityReason.RETROACTIVE_EDIT in verdict.reasons

    def test_conflicting_event_history_is_flagged(self) -> None:
        verdict = evaluate_session(make_input(has_event_conflict=True), THRESHOLDS)
        assert IntegrityReason.EVENT_CONFLICT in verdict.reasons

    def test_multiple_problems_are_all_reported(self) -> None:
        verdict = evaluate_session(
            make_input(
                elapsed_seconds=13 * 3600,
                longest_interval_seconds=13 * 3600,
                overlaps_existing=True,
            ),
            THRESHOLDS,
        )
        assert len(verdict.reasons) == 3
        # Stable ordering keeps stored reasons and tests reproducible.
        assert list(verdict.reasons) == sorted(verdict.reasons, key=lambda r: r.value)


class TestConfigurability:
    def test_thresholds_are_configurable_not_hardcoded(self) -> None:
        lenient = IntegrityThresholds(max_session_hours=24.0)
        data = make_input(elapsed_seconds=13 * 3600, longest_interval_seconds=3600)
        assert evaluate_session(data, THRESHOLDS).status is IntegrityStatus.FLAGGED
        assert evaluate_session(data, lenient).status is IntegrityStatus.OK

    def test_every_reason_has_a_user_facing_message(self) -> None:
        """Users must always be able to learn why a record was excluded."""
        for reason in IntegrityReason:
            assert reason.user_message
            assert not reason.user_message.startswith(reason.value)
