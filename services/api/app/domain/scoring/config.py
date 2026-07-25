"""Versioned scoring configuration.

Weights live in data, not in the algorithm. A season stores the exact config it launched
with (`league_seasons.scoring_config`), so changing the rules for season N+1 can never
retroactively rewrite season N's standings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Self


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Maximum points per component. These must sum to `total_points`."""

    goal_completion: int = 400
    consistency: int = 250
    focus_sessions: int = 150
    task_completion: int = 150
    group_participation: int = 50


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """All knobs the scoring algorithm reads.

    Anti-burnout design (product requirement, not an implementation detail):

    * `goal_overshoot_credit_ratio` caps what studying past the daily goal is worth, so a
      14-hour day cannot out-score a consistent week.
    * Only *scheduled* days form the consistency denominator, so planned rest days cost
      nothing.
    * `manual_time_credit` is 0.0: unverifiable time earns no competitive points.
    * `focus_sessions_target` and `tasks_target` saturate quickly — the goal is "did you
      execute your plan", not "how much can you grind".
    """

    version: str = "v1"
    total_points: int = 1000
    weights: ScoringWeights = field(default_factory=ScoringWeights)

    # A day counts as "goal met" at 100% of the daily goal; time beyond the goal earns
    # partial credit up to this multiple, then nothing further.
    goal_overshoot_credit_ratio: float = 0.25
    goal_overshoot_cap_multiple: float = 2.0

    # Consistency: fraction of scheduled days with any meaningful verified study.
    consistency_minimum_minutes: int = 20
    # Studying on unscheduled days is a small bonus, never a requirement.
    consistency_bonus_per_extra_day: int = 10
    consistency_bonus_cap: int = 30

    # Completed focus sessions (Pomodoro blocks finished, or stopwatch sessions marked as
    # going to plan) needed for full marks.
    focus_sessions_target: int = 12
    # Planned tasks completed for full marks.
    tasks_target: int = 15
    # Group participation events (encouragement given/received, room joins) for full marks.
    participation_target: int = 10

    manual_time_credit: float = 0.0

    def validated(self) -> Self:
        """Fail fast on a config that cannot produce a coherent 0–1000 score."""
        component_total = (
            self.weights.goal_completion
            + self.weights.consistency
            + self.weights.focus_sessions
            + self.weights.task_completion
            + self.weights.group_participation
        )
        if component_total != self.total_points:
            raise ValueError(
                f"Scoring weights sum to {component_total}, expected {self.total_points}."
            )
        if not 0.0 <= self.manual_time_credit <= 1.0:
            raise ValueError("manual_time_credit must be between 0 and 1.")
        if self.goal_overshoot_cap_multiple < 1.0:
            raise ValueError("goal_overshoot_cap_multiple must be at least 1.0.")
        for name, value in (
            ("focus_sessions_target", self.focus_sessions_target),
            ("tasks_target", self.tasks_target),
            ("participation_target", self.participation_target),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialise for storage on the season row."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoringConfig:
        """Rebuild a stored config so an old season can be recomputed exactly."""
        payload = dict(data)
        weights = payload.pop("weights", None)
        config = cls(**payload)
        if weights is not None:
            config = replace(config, weights=ScoringWeights(**weights))
        return config.validated()


SCORING_CONFIG_V1: ScoringConfig = ScoringConfig().validated()
