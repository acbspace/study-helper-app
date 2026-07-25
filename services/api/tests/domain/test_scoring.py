"""League scoring: deterministic tests written before rankings are exposed.

These tests are the executable specification of the product's fairness promises.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.domain.scoring import (
    SCORING_CONFIG_V1,
    DayActivity,
    ScoringConfig,
    ScoringWeights,
    WeeklyScoreInput,
    score_week,
)

MONDAY = date(2026, 7, 20)


def day(
    offset: int,
    *,
    minutes: float = 0,
    scheduled: bool = True,
    goal_minutes: int = 120,
) -> DayActivity:
    return DayActivity(
        day=MONDAY + timedelta(days=offset),
        is_scheduled=scheduled,
        verified_seconds=int(minutes * 60),
        goal_minutes=goal_minutes,
    )


def week(days: list[DayActivity], **kwargs: object) -> WeeklyScoreInput:
    return WeeklyScoreInput(user_id="u1", week_start=MONDAY, days=tuple(days), **kwargs)  # type: ignore[arg-type]


def weekdays(minutes: float, **kwargs: object) -> list[DayActivity]:
    """Mon–Fri scheduled, Sat–Sun not."""
    return [day(i, minutes=minutes, **kwargs) for i in range(5)] + [  # type: ignore[arg-type]
        day(i, minutes=0, scheduled=False) for i in (5, 6)
    ]


class TestConfig:
    def test_default_config_is_valid(self) -> None:
        assert SCORING_CONFIG_V1.validated() is SCORING_CONFIG_V1
        assert SCORING_CONFIG_V1.version == "v1"

    def test_weights_must_sum_to_the_total(self) -> None:
        broken = ScoringConfig(weights=ScoringWeights(goal_completion=500))
        with pytest.raises(ValueError, match="sum to"):
            broken.validated()

    def test_manual_time_earns_no_competitive_credit(self) -> None:
        """The product promise: manual time is visible, but never competitive."""
        assert SCORING_CONFIG_V1.manual_time_credit == 0.0

    def test_config_round_trips_through_storage(self) -> None:
        """Seasons freeze their config as JSON; it must rebuild exactly."""
        stored = SCORING_CONFIG_V1.to_dict()
        assert ScoringConfig.from_dict(stored) == SCORING_CONFIG_V1


class TestDeterminism:
    def test_identical_inputs_give_identical_scores(self) -> None:
        data = week(weekdays(120), focus_sessions_completed=8, tasks_planned=10, tasks_completed=7)
        first = score_week(data, SCORING_CONFIG_V1)
        second = score_week(data, SCORING_CONFIG_V1)
        assert first.total_points == second.total_points
        assert first.to_dict() == second.to_dict()

    def test_score_never_exceeds_one_thousand(self) -> None:
        perfect = week(
            [day(i, minutes=600) for i in range(7)],
            focus_sessions_completed=99,
            tasks_planned=99,
            tasks_completed=99,
            participation_events=99,
        )
        result = score_week(perfect, SCORING_CONFIG_V1)
        assert result.total_points <= 1000
        assert all(c.points <= c.max_points for c in result.components)

    def test_empty_week_scores_zero(self) -> None:
        result = score_week(week(weekdays(0)), SCORING_CONFIG_V1)
        assert result.total_points == 0

    def test_no_scheduled_days_scores_zero_without_crashing(self) -> None:
        """A user who scheduled no study days must not divide by zero."""
        data = week([day(i, minutes=60, scheduled=False) for i in range(7)])
        result = score_week(data, SCORING_CONFIG_V1)
        assert result.goal.points == 0
        assert result.consistency.points == 0


class TestGoalComponent:
    def test_meeting_the_goal_every_day_earns_full_marks(self) -> None:
        result = score_week(week(weekdays(120)), SCORING_CONFIG_V1)
        assert result.goal.points == 400

    def test_half_the_goal_earns_roughly_half(self) -> None:
        result = score_week(week(weekdays(60)), SCORING_CONFIG_V1)
        assert result.goal.points == 200

    def test_overshooting_the_goal_is_capped(self) -> None:
        """Studying 10x the goal must not beat studying exactly the goal by much — this is
        the core anti-burnout guarantee."""
        on_target = score_week(week(weekdays(120)), SCORING_CONFIG_V1).goal.points
        extreme = score_week(week(weekdays(1200)), SCORING_CONFIG_V1).goal.points
        assert on_target == extreme == 400

    def test_a_marathon_day_cannot_replace_a_consistent_week(self) -> None:
        """One 12-hour day must score below five ordinary days."""
        marathon = week([day(0, minutes=720)] + [day(i, minutes=0) for i in range(1, 5)])
        steady = week(weekdays(120))
        assert score_week(marathon, SCORING_CONFIG_V1).total_points < (
            score_week(steady, SCORING_CONFIG_V1).total_points
        )

    def test_days_without_a_goal_do_not_drag_the_average(self) -> None:
        days = [day(i, minutes=120) for i in range(4)] + [day(4, minutes=0, goal_minutes=0)]
        result = score_week(week(days), SCORING_CONFIG_V1)
        assert result.goal.points == 400


class TestConsistencyComponent:
    def test_studying_every_scheduled_day_earns_the_base_maximum(self) -> None:
        result = score_week(week(weekdays(120)), SCORING_CONFIG_V1)
        # Base is the weight minus the room reserved for the extra-day bonus.
        assert result.consistency.points == 250 - SCORING_CONFIG_V1.consistency_bonus_cap

    def test_scheduled_rest_days_are_never_penalised(self) -> None:
        """A user who schedules three study days and studies all three scores the same as
        one who schedules five and studies five."""
        three_days = week(
            [day(i, minutes=120) for i in range(3)]
            + [day(i, minutes=0, scheduled=False) for i in range(3, 7)]
        )
        five_days = week(weekdays(120))
        assert (
            score_week(three_days, SCORING_CONFIG_V1).consistency.points
            == score_week(five_days, SCORING_CONFIG_V1).consistency.points
        )

    def test_studying_on_unscheduled_days_is_a_bounded_bonus(self) -> None:
        base = score_week(week(weekdays(120)), SCORING_CONFIG_V1).consistency.points
        with_extra = score_week(
            week(
                [day(i, minutes=120) for i in range(5)]
                + [day(i, minutes=120, scheduled=False) for i in (5, 6)]
            ),
            SCORING_CONFIG_V1,
        ).consistency
        assert with_extra.points > base
        assert with_extra.points <= 250

    def test_token_study_does_not_count_as_a_studied_day(self) -> None:
        """Five minutes is not a study day; the threshold prevents streak-gaming."""
        result = score_week(week(weekdays(5)), SCORING_CONFIG_V1)
        assert result.consistency.detail["scheduled_days_studied"] == 0


class TestFocusAndTaskComponents:
    def test_focus_sessions_saturate_at_the_target(self) -> None:
        at_target = week(weekdays(120), focus_sessions_completed=12)
        far_past = week(weekdays(120), focus_sessions_completed=120)
        assert score_week(at_target, SCORING_CONFIG_V1).focus.points == 150
        assert score_week(far_past, SCORING_CONFIG_V1).focus.points == 150

    def test_completing_every_planned_task_at_volume_earns_full_marks(self) -> None:
        data = week(weekdays(120), tasks_planned=15, tasks_completed=15)
        assert score_week(data, SCORING_CONFIG_V1).tasks.points == 150

    def test_planning_nothing_earns_nothing(self) -> None:
        data = week(weekdays(120), tasks_planned=0, tasks_completed=0)
        result = score_week(data, SCORING_CONFIG_V1)
        assert result.tasks.points == 0
        assert result.tasks.detail["reason"] == "no_tasks_planned"

    def test_completing_more_than_planned_cannot_inflate_the_score(self) -> None:
        honest = week(weekdays(120), tasks_planned=10, tasks_completed=10)
        inflated = week(weekdays(120), tasks_planned=10, tasks_completed=999)
        assert (
            score_week(honest, SCORING_CONFIG_V1).tasks.points
            == score_week(inflated, SCORING_CONFIG_V1).tasks.points
        )

    def test_two_trivial_tasks_score_below_a_full_plan(self) -> None:
        tiny = week(weekdays(120), tasks_planned=2, tasks_completed=2)
        full = week(weekdays(120), tasks_planned=15, tasks_completed=15)
        assert score_week(tiny, SCORING_CONFIG_V1).tasks.points < (
            score_week(full, SCORING_CONFIG_V1).tasks.points
        )


class TestParticipationComponent:
    def test_participation_is_capped_low(self) -> None:
        """Socialising must never be a route to the top of a study leaderboard."""
        social_only = week(weekdays(0), participation_events=1000)
        result = score_week(social_only, SCORING_CONFIG_V1)
        assert result.participation.points == 50
        assert result.total_points == 50

    def test_negative_inputs_are_clamped(self) -> None:
        data = week(weekdays(120), participation_events=-5, focus_sessions_completed=-3)
        result = score_week(data, SCORING_CONFIG_V1)
        assert result.participation.points == 0
        assert result.focus.points == 0


class TestMonotonicity:
    @pytest.mark.parametrize("minutes", [0, 30, 60, 90, 120])
    def test_more_study_never_lowers_the_score(self, minutes: int) -> None:
        lower = score_week(week(weekdays(minutes)), SCORING_CONFIG_V1).total_points
        higher = score_week(week(weekdays(minutes + 30)), SCORING_CONFIG_V1).total_points
        assert higher >= lower

    @pytest.mark.parametrize("completed", [0, 3, 6, 9, 12])
    def test_more_completed_sessions_never_lowers_the_score(self, completed: int) -> None:
        lower = score_week(
            week(weekdays(120), focus_sessions_completed=completed), SCORING_CONFIG_V1
        ).total_points
        higher = score_week(
            week(weekdays(120), focus_sessions_completed=completed + 1), SCORING_CONFIG_V1
        ).total_points
        assert higher >= lower


class TestReproducibility:
    def test_old_config_reproduces_old_scores(self) -> None:
        """Changing the weights for a future season must not rewrite history."""
        data = week(
            weekdays(120), focus_sessions_completed=12, tasks_planned=15, tasks_completed=15
        )
        old = score_week(data, SCORING_CONFIG_V1)

        v2 = replace(
            SCORING_CONFIG_V1,
            version="v2",
            weights=ScoringWeights(
                goal_completion=300,
                consistency=350,
                focus_sessions=150,
                task_completion=150,
                group_participation=50,
            ),
        ).validated()
        new = score_week(data, v2)

        assert new.goal.points != old.goal.points
        # Recomputing with the archived config still yields the original numbers.
        replayed = score_week(data, ScoringConfig.from_dict(SCORING_CONFIG_V1.to_dict()))
        assert replayed.to_dict() == old.to_dict()

    def test_breakdown_explains_every_component(self) -> None:
        """A score users cannot audit is a score they will not trust."""
        data = week(weekdays(120), focus_sessions_completed=6, tasks_planned=10, tasks_completed=5)
        result = score_week(data, SCORING_CONFIG_V1)
        payload = result.to_dict()
        assert payload["total_points"] == result.total_points
        assert len(payload["components"]) == 5
        assert all(component["detail"] for component in payload["components"])
        assert payload["scoring_version"] == "v1"


def test_exclusions_are_carried_into_the_breakdown() -> None:
    """Users must be told which time was excluded and why."""
    data = week(weekdays(120), excluded_seconds=3600, exclusion_reasons=("marathon_session",))
    result = score_week(data, SCORING_CONFIG_V1)
    assert result.excluded_seconds == 3600
    assert result.to_dict()["exclusion_reasons"] == ["marathon_session"]
