"""Competitive-integrity rules for study sessions.

Design constraints from the product brief, encoded here:

* Nothing is ever silently deleted. Rules only *flag*, and every flag carries a reason the
  user can be shown.
* Personal statistics keep flagged time; League scoring drops it. Manual entries are
  always visible personally and always worth zero competitively.
* Thresholds are configuration, not constants, so they can be tuned without a deploy.
* No surveillance: every signal here comes from timestamps the app already produces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.core.clock import ensure_utc
from app.models.enums import IntegrityStatus, SessionSource


class IntegrityReason(StrEnum):
    MARATHON_SESSION = "marathon_session"
    LONG_SINGLE_INTERVAL = "long_single_interval"
    OVERLAPPING_SESSION = "overlapping_session"
    TIMELINE_INVALID = "timeline_invalid"
    CLOCK_SKEW = "clock_skew"
    RETROACTIVE_EDIT = "retroactive_edit"
    EVENT_CONFLICT = "event_conflict"
    MANUAL_ENTRY = "manual_entry"

    @property
    def user_message(self) -> str:
        """Plain-language explanation shown when a record is excluded from competition."""
        return _USER_MESSAGES[self]


_USER_MESSAGES: dict[IntegrityReason, str] = {
    IntegrityReason.MARATHON_SESSION: (
        "This session ran longer than a single healthy study block, so it is not counted "
        "toward League Points."
    ),
    IntegrityReason.LONG_SINGLE_INTERVAL: (
        "This session ran without a break for an unusually long time, so it is not counted "
        "toward League Points."
    ),
    IntegrityReason.OVERLAPPING_SESSION: (
        "This session overlaps another recorded session, so only one of them can count "
        "toward League Points."
    ),
    IntegrityReason.TIMELINE_INVALID: (
        "The timer history for this session is inconsistent, so it is not counted toward "
        "League Points."
    ),
    IntegrityReason.CLOCK_SKEW: (
        "This session's times differ substantially from server time, so it is not counted "
        "toward League Points."
    ),
    IntegrityReason.RETROACTIVE_EDIT: (
        "This session was edited long after it ended, so it is not counted toward League Points."
    ),
    IntegrityReason.EVENT_CONFLICT: (
        "Two different versions of this session's timer history were received, so it is "
        "not counted toward League Points."
    ),
    IntegrityReason.MANUAL_ENTRY: (
        "Manually entered time appears in your personal statistics but does not earn League Points."
    ),
}


@dataclass(frozen=True, slots=True)
class IntegrityThresholds:
    """Tunable limits. Built from Settings at the edge; defaults mirror config defaults."""

    max_session_hours: float = 12.0
    max_single_interval_hours: float = 6.0
    max_clock_skew_minutes: float = 10.0
    retro_edit_window_hours: float = 48.0


@dataclass(frozen=True, slots=True)
class SessionIntegrityInput:
    """Facts about one session, gathered by the caller."""

    source: SessionSource
    started_at: datetime
    ended_at: datetime | None
    elapsed_seconds: int
    longest_interval_seconds: int
    timeline_problems: tuple[str, ...] = ()
    latest_event_at: datetime | None = None
    server_received_at: datetime | None = None
    overlaps_existing: bool = False
    has_event_conflict: bool = False


@dataclass(frozen=True, slots=True)
class IntegrityVerdict:
    status: IntegrityStatus
    reasons: tuple[IntegrityReason, ...]

    @property
    def counts_for_league(self) -> bool:
        """Whether this session may contribute League Points at all."""
        return self.status is IntegrityStatus.OK

    def messages(self) -> tuple[str, ...]:
        return tuple(reason.user_message for reason in self.reasons)


def evaluate_session(
    data: SessionIntegrityInput, thresholds: IntegrityThresholds
) -> IntegrityVerdict:
    """Classify a session for competitive purposes.

    Returns a verdict; the caller persists it and appends an audit entry. Manual entries
    are `EXCLUDED` (not flagged) because they are a legitimate, expected feature — the
    user did nothing wrong, the time simply cannot be verified.
    """
    reasons: list[IntegrityReason] = []

    if data.source is SessionSource.MANUAL:
        return IntegrityVerdict(IntegrityStatus.EXCLUDED, (IntegrityReason.MANUAL_ENTRY,))

    if data.timeline_problems:
        reasons.append(IntegrityReason.TIMELINE_INVALID)

    if data.has_event_conflict:
        reasons.append(IntegrityReason.EVENT_CONFLICT)

    if data.elapsed_seconds > thresholds.max_session_hours * 3600:
        reasons.append(IntegrityReason.MARATHON_SESSION)

    if data.longest_interval_seconds > thresholds.max_single_interval_hours * 3600:
        reasons.append(IntegrityReason.LONG_SINGLE_INTERVAL)

    if data.overlaps_existing:
        reasons.append(IntegrityReason.OVERLAPPING_SESSION)

    if data.latest_event_at is not None and data.server_received_at is not None:
        # Only *future-dated* claims count as skew. Arriving late is normal and expected:
        # that is what offline support is for.
        skew = (
            ensure_utc(data.latest_event_at) - ensure_utc(data.server_received_at)
        ).total_seconds()
        if skew > thresholds.max_clock_skew_minutes * 60:
            reasons.append(IntegrityReason.CLOCK_SKEW)

    if data.ended_at is not None and data.server_received_at is not None:
        age = ensure_utc(data.server_received_at) - ensure_utc(data.ended_at)
        if age > timedelta(hours=thresholds.retro_edit_window_hours):
            reasons.append(IntegrityReason.RETROACTIVE_EDIT)

    if not reasons:
        return IntegrityVerdict(IntegrityStatus.OK, ())

    # Deduplicate while keeping a stable, testable order.
    unique = tuple(sorted(set(reasons), key=lambda reason: reason.value))
    return IntegrityVerdict(IntegrityStatus.FLAGGED, unique)
