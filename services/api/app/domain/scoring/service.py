"""The weekly League Points calculation.

Pure and total: `score_week(input, config)` reads nothing outside its arguments, so a
score can be recomputed identically months later from stored inputs.

What the design deliberately rewards:

* **Meeting the goal you set** (400) — not exceeding it. Overshooting earns heavily
  discounted credit and stops entirely at `goal_overshoot_cap_multiple`, so no amount of
  grinding beats a consistent week.
* **Consistency on days you chose** (250) — the denominator is your scheduled days, so
  rest days you planned cost nothing, and studying on an unscheduled day is a small bonus.
* **Finishing what you start** (150 focus + 150 tasks) — completed sessions and completed
  planned tasks, both saturating at a modest target.
* **Showing up for others** (50) — capped low on purpose; it must never become the path to
  the top of a study leaderboard.

Manual time contributes zero (`manual_time_credit`), and flagged time is excluded before
it ever reaches this function.
"""

from __future__ import annotations

from app.domain.scoring.config import ScoringConfig
from app.domain.scoring.models import ComponentScore, WeeklyScoreBreakdown, WeeklyScoreInput


def score_week(data: WeeklyScoreInput, config: ScoringConfig) -> WeeklyScoreBreakdown:
    """Compute a 0–1000 weekly score. Deterministic for a given (input, config)."""
    config.validated()
    return WeeklyScoreBreakdown(
        user_id=data.user_id,
        week_start=data.week_start,
        scoring_version=config.version,
        goal=_score_goal(data, config),
        consistency=_score_consistency(data, config),
        focus=_score_focus(data, config),
        tasks=_score_tasks(data, config),
        participation=_score_participation(data, config),
        excluded_seconds=data.excluded_seconds,
        exclusion_reasons=data.exclusion_reasons,
    )


def _score_goal(data: WeeklyScoreInput, config: ScoringConfig) -> ComponentScore:
    """Average per-scheduled-day goal attainment, with capped overshoot credit."""
    maximum = config.weights.goal_completion
    scheduled = data.scheduled_days
    if not scheduled:
        return ComponentScore(
            "goal_completion", 0, maximum, {"reason": "no_scheduled_days", "days": 0}
        )

    attainments: list[float] = []
    days_met = 0
    for day in scheduled:
        if day.goal_minutes <= 0:
            # No goal set for the day: it cannot be scored, and shouldn't drag the average.
            continue
        target = day.goal_minutes
        achieved = day.verified_minutes
        base = min(achieved / target, 1.0)
        if achieved > target:
            overshoot_room = target * (config.goal_overshoot_cap_multiple - 1.0)
            overshoot = min(achieved - target, overshoot_room)
            bonus = (
                0.0
                if overshoot_room <= 0
                else (overshoot / overshoot_room) * config.goal_overshoot_credit_ratio
            )
        else:
            bonus = 0.0
        if achieved >= target:
            days_met += 1
        attainments.append(min(base + bonus, 1.0))

    if not attainments:
        return ComponentScore(
            "goal_completion", 0, maximum, {"reason": "no_goal_set", "days": len(scheduled)}
        )

    average = sum(attainments) / len(attainments)
    points = _cap(round(average * maximum), maximum)
    return ComponentScore(
        "goal_completion",
        points,
        maximum,
        {
            "scheduled_days": len(scheduled),
            "days_goal_met": days_met,
            "average_attainment": round(average, 4),
            "overshoot_credit_ratio": config.goal_overshoot_credit_ratio,
        },
    )


def _score_consistency(data: WeeklyScoreInput, config: ScoringConfig) -> ComponentScore:
    """Share of scheduled days actually studied, plus a small unscheduled-day bonus."""
    maximum = config.weights.consistency
    scheduled = data.scheduled_days
    threshold_seconds = config.consistency_minimum_minutes * 60

    if not scheduled:
        return ComponentScore("consistency", 0, maximum, {"reason": "no_scheduled_days"})

    days_studied = sum(1 for day in scheduled if day.verified_seconds >= threshold_seconds)
    base_ratio = days_studied / len(scheduled)
    base_points = base_ratio * (maximum - config.consistency_bonus_cap)

    extra_days = sum(
        1 for day in data.days if not day.is_scheduled and day.verified_seconds >= threshold_seconds
    )
    bonus = min(extra_days * config.consistency_bonus_per_extra_day, config.consistency_bonus_cap)

    points = _cap(round(base_points + bonus), maximum)
    return ComponentScore(
        "consistency",
        points,
        maximum,
        {
            "scheduled_days": len(scheduled),
            "scheduled_days_studied": days_studied,
            "extra_days_studied": extra_days,
            "minimum_minutes": config.consistency_minimum_minutes,
            "bonus_points": bonus,
        },
    )


def _score_focus(data: WeeklyScoreInput, config: ScoringConfig) -> ComponentScore:
    """Completed focus blocks, saturating at the configured target."""
    maximum = config.weights.focus_sessions
    completed = max(data.focus_sessions_completed, 0)
    ratio = min(completed / config.focus_sessions_target, 1.0)
    points = _cap(round(ratio * maximum), maximum)
    return ComponentScore(
        "focus_sessions",
        points,
        maximum,
        {"completed": completed, "target": config.focus_sessions_target},
    )


def _score_tasks(data: WeeklyScoreInput, config: ScoringConfig) -> ComponentScore:
    """Planned task execution.

    Scored as completion *rate* against what the user planned, scaled by how much they
    planned relative to the target. Planning two trivial tasks and finishing both should
    not equal a full week of planned work, but planning nothing at all scores zero rather
    than dividing by zero.
    """
    maximum = config.weights.task_completion
    planned = max(data.tasks_planned, 0)
    completed = max(min(data.tasks_completed, planned), 0) if planned else 0

    if planned == 0:
        return ComponentScore(
            "task_completion", 0, maximum, {"reason": "no_tasks_planned", "planned": 0}
        )

    completion_rate = completed / planned
    volume_factor = min(planned / config.tasks_target, 1.0)
    points = _cap(round(completion_rate * volume_factor * maximum), maximum)
    return ComponentScore(
        "task_completion",
        points,
        maximum,
        {
            "planned": planned,
            "completed": completed,
            "completion_rate": round(completion_rate, 4),
            "volume_factor": round(volume_factor, 4),
            "target": config.tasks_target,
        },
    )


def _score_participation(data: WeeklyScoreInput, config: ScoringConfig) -> ComponentScore:
    """Encouragement and group presence — capped low by design."""
    maximum = config.weights.group_participation
    events = max(data.participation_events, 0)
    ratio = min(events / config.participation_target, 1.0)
    points = _cap(round(ratio * maximum), maximum)
    return ComponentScore(
        "group_participation",
        points,
        maximum,
        {"events": events, "target": config.participation_target},
    )


def _cap(points: float, maximum: int) -> int:
    return int(max(0, min(points, maximum)))
