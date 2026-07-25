"""Mission progress, evaluated from the same weekly facts that produce League Points.

Adding a *mission* is a data insert; adding a *metric* is a code change, because each metric
needs an evaluator here (see `MissionMetric`). That split is deliberate: product can ship new
nudges without a deploy, but nothing can silently invent a new way to score.

Missions are evaluated **per week** and recomputed from scratch on every scoring run, so a
retried run converges on the same number instead of accumulating — the same idempotency rule
the weekly score follows.

Every metric here rewards finishing something you planned. None of them reward raw hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from app.domain.scoring.config import ScoringConfig
from app.domain.scoring.models import DayActivity, WeeklyScoreInput
from app.models.enums import MissionMetric


@dataclass(frozen=True, slots=True)
class MissionInputs:
    """Facts the scorer does not need but missions do."""

    early_sessions_completed: int = 0


def evaluate(
    facts: WeeklyScoreInput, config: ScoringConfig, extra: MissionInputs
) -> dict[str, int]:
    """Progress for every known metric, for the week described by `facts`."""
    threshold_seconds = config.consistency_minimum_minutes * 60
    return {
        MissionMetric.PLANNED_SESSIONS_COMPLETED.value: facts.focus_sessions_completed,
        MissionMetric.DAILY_GOAL_REACHED.value: sum(1 for day in facts.days if _goal_met(day)),
        MissionMetric.SCHEDULED_DAYS_STUDIED.value: sum(
            1 for day in facts.scheduled_days if day.verified_seconds >= threshold_seconds
        ),
        MissionMetric.EARLY_SESSION_COMPLETED.value: extra.early_sessions_completed,
        MissionMetric.TASKS_COMPLETED.value: facts.tasks_completed,
        MissionMetric.RECOVERED_AFTER_MISS.value: _recoveries(facts),
    }


def _goal_met(day: DayActivity) -> bool:
    return day.goal_minutes > 0 and day.verified_seconds >= day.goal_minutes * 60


def _recoveries(facts: WeeklyScoreInput) -> int:
    """Times the user missed a scheduled day and hit the goal on the next scheduled one.

    This is the anti-spiral mission: one bad day is normal, and coming back from it is the
    behaviour worth rewarding — so it counts the *recovery*, never the miss.
    """
    recoveries = 0
    for previous, current in pairwise(facts.scheduled_days):
        if not _goal_met(previous) and _goal_met(current):
            recoveries += 1
    return recoveries
