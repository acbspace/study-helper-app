"""D-Day goals: the countdown, weekly pacing from verified time, and milestones."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.study import StudySession, Subject
from app.models.user import User

# The `user` fixture lives in Asia/Seoul, and the countdown is computed in the user's zone —
# so the reference "today" must be their local date, not UTC's.
_USER_TZ = ZoneInfo("Asia/Seoul")


def _future(days: int) -> str:
    return (datetime.now(_USER_TZ).date() + timedelta(days=days)).isoformat()


class TestGoalCrud:
    async def test_create_and_countdown(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/goals",
            json={
                "title": "Pass the bar exam",
                "target_date": _future(30),
                "target_weekly_minutes": 600,
                "milestones": [{"title": "Finish outlines"}],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Pass the bar exam"
        assert body["days_remaining"] == 30
        assert body["is_overdue"] is False
        assert body["milestones_total"] == 1
        assert body["milestones"][0]["title"] == "Finish outlines"

    async def test_overdue_goal_is_flagged(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/goals",
            json={"title": "Late goal", "target_date": _future(-3)},
            headers=auth_headers,
        )
        assert response.json()["days_remaining"] == -3
        assert response.json()["is_overdue"] is True

    async def test_list_hides_finished_by_default(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        created = await client.post("/goals", json={"title": "Ongoing"}, headers=auth_headers)
        goal_id = created.json()["id"]
        done = await client.post("/goals", json={"title": "Wrapped up"}, headers=auth_headers)
        await client.patch(
            f"/goals/{done.json()['id']}", json={"status": "completed"}, headers=auth_headers
        )

        active = await client.get("/goals", headers=auth_headers)
        assert [g["id"] for g in active.json()] == [goal_id]

        everything = await client.get(
            "/goals", params={"include_finished": True}, headers=auth_headers
        )
        assert len(everything.json()) == 2

    async def test_completing_sets_completed_at(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        created = await client.post("/goals", json={"title": "Finish me"}, headers=auth_headers)
        updated = await client.patch(
            f"/goals/{created.json()['id']}", json={"status": "completed"}, headers=auth_headers
        )
        assert updated.json()["status"] == "completed"
        assert updated.json()["completed_at"] is not None

    async def test_clearing_the_target_date(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        created = await client.post(
            "/goals", json={"title": "Someday", "target_date": _future(10)}, headers=auth_headers
        )
        updated = await client.patch(
            f"/goals/{created.json()['id']}", json={"clear_target_date": True}, headers=auth_headers
        )
        assert updated.json()["target_date"] is None
        assert updated.json()["days_remaining"] is None

    async def test_delete(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        created = await client.post("/goals", json={"title": "Temp"}, headers=auth_headers)
        goal_id = created.json()["id"]
        assert (await client.delete(f"/goals/{goal_id}", headers=auth_headers)).status_code == 204
        assert (await client.get(f"/goals/{goal_id}", headers=auth_headers)).status_code == 404

    async def test_cannot_touch_another_users_goal(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        created = await client.post("/goals", json={"title": "Mine"}, headers=auth_headers)
        goal_id = created.json()["id"]
        assert (
            await client.get(f"/goals/{goal_id}", headers=other_auth_headers)
        ).status_code == 404
        assert (
            await client.patch(
                f"/goals/{goal_id}", json={"title": "Hijacked"}, headers=other_auth_headers
            )
        ).status_code == 404

    async def test_empty_milestones_are_dropped(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/goals",
            json={"title": "Clean", "milestones": [{"title": "   "}, {"title": "Real one"}]},
            headers=auth_headers,
        )
        # Whitespace-only titles are rejected by validation before they reach the service.
        assert response.status_code == 422


class TestWeeklyPacing:
    async def test_verified_study_counts_toward_the_weekly_target(
        self, client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession, user: User
    ) -> None:
        subject = Subject(user_id=user.id, name="Contracts", color_hex="#4F6BED")
        db.add(subject)
        await db.flush()
        # 90 minutes of verified time earlier today (in the user's week).
        now = datetime.now(UTC)
        db.add(
            StudySession(
                id=uuid.uuid4(),
                user_id=user.id,
                subject_id=subject.id,
                source="timer",
                status="completed",
                started_at=now - timedelta(hours=2),
                ended_at=now - timedelta(minutes=30),
                duration_seconds=90 * 60,
                integrity_status="ok",
            )
        )
        await db.commit()

        created = await client.post(
            "/goals",
            json={"title": "Study hard", "target_weekly_minutes": 180},
            headers=auth_headers,
        )
        assert created.json()["week_verified_minutes"] == 90
        assert created.json()["weekly_progress"] == 0.5

    async def test_progress_caps_at_one(
        self, client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession, user: User
    ) -> None:
        subject = Subject(user_id=user.id, name="Torts", color_hex="#4F6BED")
        db.add(subject)
        await db.flush()
        now = datetime.now(UTC)
        db.add(
            StudySession(
                id=uuid.uuid4(),
                user_id=user.id,
                subject_id=subject.id,
                source="timer",
                status="completed",
                started_at=now - timedelta(hours=3),
                ended_at=now,
                duration_seconds=200 * 60,
                integrity_status="ok",
            )
        )
        await db.commit()

        created = await client.post(
            "/goals", json={"title": "Overshoot", "target_weekly_minutes": 60}, headers=auth_headers
        )
        assert created.json()["weekly_progress"] == 1.0


class TestAuthentication:
    async def test_endpoints_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/goals")).status_code == 401
        assert (await client.post("/goals", json={"title": "x"})).status_code == 401
