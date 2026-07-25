"""The seasonal league: placement, weekly scoring from real activity, standings, close-out.

Scoring is exercised end to end — activity is created through the public API, then the real
scoring run turns it into points — so these tests cover the join between "what the user did"
and "what the league says", which is where a scoring bug would actually hurt.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.league.service import LeagueService
from app.domain.scoring.config import SCORING_CONFIG_V1
from app.models.enums import MissionMetric, SeasonStatus
from app.models.league import LeagueCategory, LeagueDivision, LeagueMission, LeagueSeason


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


@pytest_asyncio.fixture
async def season(db: AsyncSession) -> LeagueSeason:
    """An active four-week season starting this Monday, with a Bronze entry division."""
    db.add(
        LeagueCategory(
            slug="general_productivity", name="General productivity", sort_order=0, is_active=True
        )
    )
    starts_on = _monday(datetime.now(UTC).date())
    record = LeagueSeason(
        name="Test Season",
        starts_on=starts_on,
        ends_on=starts_on + timedelta(days=27),
        status=SeasonStatus.ACTIVE.value,
        scoring_config=SCORING_CONFIG_V1.to_dict(),
        promotion_rate=0.2,
        relegation_rate=0.2,
    )
    db.add(record)
    await db.flush()
    db.add(LeagueDivision(season_id=record.id, tier=0, name="Bronze"))
    await db.commit()
    await db.refresh(record)
    return record


async def _register(
    client: AsyncClient, *, email: str, username: str
) -> tuple[str, dict[str, str]]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "test-passphrase-9x",
            "username": username,
            "display_name": username.title(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


async def _study_and_plan(client: AsyncClient, headers: dict[str, str]) -> None:
    """Produce a completed focus session and a completed planned task for today."""
    subject = await client.post("/subjects", json={"name": "Algorithms"}, headers=headers)
    subject_id = subject.json()["id"]

    started = await client.post(
        "/study-sessions/start", json={"subject_id": subject_id}, headers=headers
    )
    assert started.status_code in (200, 201), started.text
    session_id = started.json()["id"]
    stopped = await client.post(
        f"/study-sessions/{session_id}/stop",
        json={"went_as_planned": True},
        headers=headers,
    )
    assert stopped.status_code == 200, stopped.text

    today = datetime.now(UTC).date().isoformat()
    task = await client.post(
        f"/plans/{today}/tasks", json={"title": "Review recursion"}, headers=headers
    )
    await client.patch(f"/tasks/{task.json()['id']}", json={"status": "done"}, headers=headers)


class TestEnrollment:
    async def test_enrolling_places_you_in_a_cohort(
        self, client: AsyncClient, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")

        response = await client.post("/league/enroll", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["division_name"] == "Bronze"
        assert body["placement"] == "provisional"
        assert body["cohort_size"] == 1
        assert body["rank"] == 1
        assert body["total_points"] == 0

    async def test_enrolling_twice_is_idempotent(
        self, client: AsyncClient, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        first = await client.post("/league/enroll", headers=headers)
        second = await client.post("/league/enroll", headers=headers)
        assert first.json()["cohort_id"] == second.json()["cohort_id"]
        assert second.json()["cohort_size"] == 1

    async def test_current_requires_enrollment(
        self, client: AsyncClient, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        response = await client.get("/league/current", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_enrolled"

    async def test_without_a_season_there_is_no_league(self, client: AsyncClient) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        response = await client.post("/league/enroll", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "no_active_season"


class TestScoringRun:
    async def test_activity_becomes_points(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        await client.post("/league/enroll", headers=headers)
        await _study_and_plan(client, headers)

        scored = await LeagueService(db).run_weekly_scoring(season=season, week_index=0)
        assert scored == 1

        standing = await client.get("/league/current", headers=headers)
        assert standing.json()["total_points"] > 0
        assert standing.json()["weeks"] == [
            {"week_index": 0, "points": standing.json()["total_points"]}
        ]

    async def test_breakdown_explains_the_score(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        await client.post("/league/enroll", headers=headers)
        await _study_and_plan(client, headers)
        await LeagueService(db).run_weekly_scoring(season=season, week_index=0)

        response = await client.get("/league/breakdown", params={"week_index": 0}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["scoring_version"] == SCORING_CONFIG_V1.version
        names = {component["name"]: component for component in body["components"]}
        assert set(names) == {
            "goal_completion",
            "consistency",
            "focus_sessions",
            "task_completion",
            "group_participation",
        }
        # The finished session and the completed task both earned something.
        assert names["focus_sessions"]["points"] > 0
        assert names["task_completion"]["points"] > 0
        assert names["focus_sessions"]["max_points"] == 150

    async def test_rerunning_a_week_does_not_double_count(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        await client.post("/league/enroll", headers=headers)
        await _study_and_plan(client, headers)

        service = LeagueService(db)
        await service.run_weekly_scoring(season=season, week_index=0)
        first = (await client.get("/league/current", headers=headers)).json()["total_points"]
        await service.run_weekly_scoring(season=season, week_index=0)
        second = (await client.get("/league/current", headers=headers)).json()["total_points"]

        assert first == second

    async def test_unscored_week_is_reported_clearly(
        self, client: AsyncClient, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        await client.post("/league/enroll", headers=headers)

        response = await client.get("/league/breakdown", params={"week_index": 3}, headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "score_not_found"


class TestMissions:
    async def test_missions_report_progress_after_scoring(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        db.add(
            LeagueMission(
                season_id=season.id,
                slug="finish-what-you-start",
                title="Finish what you start",
                description="Complete 1 focus session.",
                metric=MissionMetric.PLANNED_SESSIONS_COMPLETED.value,
                target=1,
                reward_points=20,
            )
        )
        await db.commit()

        _, headers = await _register(client, email="a@example.com", username="alice")
        await client.post("/league/enroll", headers=headers)

        before = await client.get("/league/missions", headers=headers)
        assert before.status_code == 200
        assert before.json()[0]["progress"] == 0
        assert before.json()[0]["completed"] is False

        await _study_and_plan(client, headers)
        await LeagueService(db).run_weekly_scoring(season=season, week_index=0)

        after = (await client.get("/league/missions", headers=headers)).json()
        assert after[0]["progress"] == 1
        assert after[0]["completed"] is True
        assert after[0]["target"] == 1

    async def test_missions_are_recomputed_not_accumulated(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        db.add(
            LeagueMission(
                season_id=season.id,
                slug="tasks",
                title="Tick things off",
                description="Complete 5 planned tasks.",
                metric=MissionMetric.TASKS_COMPLETED.value,
                target=5,
                reward_points=20,
            )
        )
        await db.commit()

        _, headers = await _register(client, email="a@example.com", username="alice")
        await client.post("/league/enroll", headers=headers)
        await _study_and_plan(client, headers)

        service = LeagueService(db)
        await service.run_weekly_scoring(season=season, week_index=0)
        await service.run_weekly_scoring(season=season, week_index=0)

        missions = (await client.get("/league/missions", headers=headers)).json()
        # One completed task, scored twice — still one.
        assert missions[0]["progress"] == 1


class TestLeaderboard:
    async def test_cohort_is_ranked_by_points(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        a_id, a = await _register(client, email="a@example.com", username="alice")
        b_id, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/league/enroll", headers=a)
        await client.post("/league/enroll", headers=b)
        # Only Alice does any work this week.
        await _study_and_plan(client, a)

        await LeagueService(db).run_weekly_scoring(season=season, week_index=0)

        board = await client.get("/league/leaderboard", headers=a)
        assert board.status_code == 200
        entries = board.json()
        assert [entry["rank"] for entry in entries] == [1, 2]
        assert entries[0]["user"]["id"] == a_id
        assert entries[0]["is_me"] is True
        assert entries[0]["total_points"] > entries[1]["total_points"]
        assert entries[1]["user"]["id"] == b_id

        # Bob sees the same ladder, from his own perspective.
        bobs_view = (await client.get("/league/leaderboard", headers=b)).json()
        assert bobs_view[1]["is_me"] is True


class TestSeasonCloseOut:
    async def test_close_assigns_ranks_and_outcomes(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        _, a = await _register(client, email="a@example.com", username="alice")
        _, b = await _register(client, email="b@example.com", username="bob")
        await client.post("/league/enroll", headers=a)
        await client.post("/league/enroll", headers=b)
        await _study_and_plan(client, a)

        service = LeagueService(db)
        await service.run_weekly_scoring(season=season, week_index=0)
        closed = await service.close_season(season)
        assert closed == 2

        history = (await client.get("/league/history", headers=a)).json()
        assert history[0]["final_rank"] == 1
        assert history[0]["outcome"] in {"promoted", "retained"}

        # Bob never scored, so he is unranked rather than relegated.
        bobs_history = (await client.get("/league/history", headers=b)).json()
        assert bobs_history[0]["outcome"] == "unranked"

    async def test_closing_ends_the_season(
        self, client: AsyncClient, db: AsyncSession, season: LeagueSeason
    ) -> None:
        _, headers = await _register(client, email="a@example.com", username="alice")
        await client.post("/league/enroll", headers=headers)
        await LeagueService(db).close_season(season)

        response = await client.get("/league/current", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "no_active_season"


class TestAuthentication:
    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/league/current")).status_code == 401
        assert (await client.get("/league/leaderboard")).status_code == 401
        assert (await client.post("/league/enroll")).status_code == 401
