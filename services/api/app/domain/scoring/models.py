"""Value objects for league scoring.

The input is *facts already gathered* — the scoring function never queries anything. That
separation is what lets the whole ruleset be unit-tested without a database and recomputed
for any past week.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class DayActivity:
    """One local day of a user's week."""

    day: date
    is_scheduled: bool
    verified_seconds: int
    manual_seconds: int = 0
    excluded_seconds: int = 0
    goal_minutes: int = 0

    @property
    def verified_minutes(self) -> float:
        return self.verified_seconds / 60


@dataclass(frozen=True, slots=True)
class WeeklyScoreInput:
    """Everything the scorer needs about one user's week."""

    user_id: str
    week_start: date
    days: tuple[DayActivity, ...]
    focus_sessions_completed: int = 0
    tasks_planned: int = 0
    tasks_completed: int = 0
    participation_events: int = 0
    excluded_seconds: int = 0
    exclusion_reasons: tuple[str, ...] = ()

    @property
    def scheduled_days(self) -> tuple[DayActivity, ...]:
        return tuple(day for day in self.days if day.is_scheduled)


@dataclass(frozen=True, slots=True)
class ComponentScore:
    """One scoring component, with the numbers behind it.

    `detail` is surfaced to users in the score-breakdown screen: a score nobody can explain
    is a score nobody trusts.
    """

    name: str
    points: int
    max_points: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        return 0.0 if self.max_points == 0 else round(self.points / self.max_points, 4)


@dataclass(frozen=True, slots=True)
class WeeklyScoreBreakdown:
    user_id: str
    week_start: date
    scoring_version: str
    goal: ComponentScore
    consistency: ComponentScore
    focus: ComponentScore
    tasks: ComponentScore
    participation: ComponentScore
    excluded_seconds: int = 0
    exclusion_reasons: tuple[str, ...] = ()

    @property
    def components(self) -> tuple[ComponentScore, ...]:
        return (self.goal, self.consistency, self.focus, self.tasks, self.participation)

    @property
    def total_points(self) -> int:
        return sum(component.points for component in self.components)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "week_start": self.week_start.isoformat(),
            "scoring_version": self.scoring_version,
            "total_points": self.total_points,
            "components": [
                {
                    "name": component.name,
                    "points": component.points,
                    "max_points": component.max_points,
                    "detail": component.detail,
                }
                for component in self.components
            ],
            "excluded_seconds": self.excluded_seconds,
            "exclusion_reasons": list(self.exclusion_reasons),
        }
