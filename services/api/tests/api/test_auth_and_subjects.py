"""Authentication, authorization boundaries, subjects, and the planner."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.study import Subject
from app.models.user import User


class TestRegistration:
    async def test_register_returns_tokens_and_profile(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "new@example.com",
                "password": "verysecure123",
                "username": "newbie",
                "timezone": "Europe/Berlin",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["user"]["profile"]["username"] == "newbie"
        assert body["user"]["settings"]["timezone"] == "Europe/Berlin"
        assert body["tokens"]["access_token"]
        assert "password" not in response.text

    async def test_duplicate_email_is_rejected(self, client: AsyncClient, user: User) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": user.email, "password": "verysecure123", "username": "different"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "email_already_registered"

    async def test_duplicate_username_is_rejected(self, client: AsyncClient, user: User) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "unique@example.com",
                "password": "verysecure123",
                "username": user.profile.username,
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "username_taken"

    async def test_email_uniqueness_is_case_insensitive(
        self, client: AsyncClient, user: User
    ) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": user.email.upper(),
                "password": "verysecure123",
                "username": "casetest",
            },
        )
        assert response.status_code == 409

    async def test_short_password_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={"email": "weak@example.com", "password": "123", "username": "weakling"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_unknown_timezone_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/auth/register",
            json={
                "email": "tz@example.com",
                "password": "verysecure123",
                "username": "tzuser",
                "timezone": "Mars/Olympus_Mons",
            },
        )
        assert response.status_code == 422


class TestLogin:
    async def test_valid_credentials_return_tokens(self, client: AsyncClient, user: User) -> None:
        response = await client.post(
            "/auth/login", json={"email": user.email, "password": "password123"}
        )
        assert response.status_code == 200
        assert response.json()["tokens"]["token_type"] == "Bearer"

    async def test_wrong_password_is_rejected(self, client: AsyncClient, user: User) -> None:
        response = await client.post(
            "/auth/login", json={"email": user.email, "password": "wrongpassword"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    async def test_unknown_email_gives_the_same_error_as_a_wrong_password(
        self, client: AsyncClient, user: User
    ) -> None:
        """Different messages would let an attacker enumerate registered accounts."""
        unknown = await client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "password123"}
        )
        wrong = await client.post(
            "/auth/login", json={"email": user.email, "password": "wrongpassword"}
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["error"] == wrong.json()["error"]


class TestTokens:
    async def test_refresh_rotates_the_token(self, client: AsyncClient, user: User) -> None:
        login = await client.post(
            "/auth/login", json={"email": user.email, "password": "password123"}
        )
        original = login.json()["tokens"]["refresh_token"]

        refreshed = await client.post("/auth/refresh", json={"refresh_token": original})
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] != original

    async def test_reusing_a_rotated_token_revokes_the_session(
        self, client: AsyncClient, user: User
    ) -> None:
        """Token reuse means it leaked; the whole family dies."""
        login = await client.post(
            "/auth/login", json={"email": user.email, "password": "password123"}
        )
        original = login.json()["tokens"]["refresh_token"]
        rotated = (await client.post("/auth/refresh", json={"refresh_token": original})).json()[
            "refresh_token"
        ]

        replayed = await client.post("/auth/refresh", json={"refresh_token": original})
        assert replayed.status_code == 401

        # The legitimate successor is revoked too.
        assert (
            await client.post("/auth/refresh", json={"refresh_token": rotated})
        ).status_code == 401

    async def test_garbage_token_is_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401

    async def test_missing_bearer_prefix_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        raw = auth_headers["Authorization"].removeprefix("Bearer ")
        assert (await client.get("/me", headers={"Authorization": raw})).status_code == 401

    async def test_logout_revokes_the_refresh_token(self, client: AsyncClient, user: User) -> None:
        login = await client.post(
            "/auth/login", json={"email": user.email, "password": "password123"}
        )
        token = login.json()["tokens"]["refresh_token"]
        assert (await client.post("/auth/logout", json={"refresh_token": token})).status_code == 204
        assert (
            await client.post("/auth/refresh", json={"refresh_token": token})
        ).status_code == 401


class TestProfileAndSettings:
    async def test_me_returns_the_current_user(
        self, client: AsyncClient, auth_headers: dict[str, str], user: User
    ) -> None:
        response = await client.get("/me", headers=auth_headers)
        assert response.json()["email"] == user.email

    async def test_settings_can_be_updated(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.patch(
            "/me/settings",
            json={"daily_goal_minutes": 240, "scheduled_study_days": 0b1111111},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["settings"]["daily_goal_minutes"] == 240

    async def test_stale_version_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """Two devices editing goals must not silently overwrite each other."""
        await client.patch("/me/settings", json={"daily_goal_minutes": 200}, headers=auth_headers)
        response = await client.patch(
            "/me/settings",
            json={"daily_goal_minutes": 300, "expected_version": 1},
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "version_conflict"

    async def test_out_of_range_goal_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.patch(
            "/me/settings", json={"daily_goal_minutes": 5000}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_unknown_field_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        """A typo in a client field name should fail loudly, not silently do nothing."""
        response = await client.patch(
            "/me/settings", json={"daily_goal_minuts": 240}, headers=auth_headers
        )
        assert response.status_code == 422


class TestSubjects:
    async def test_create_and_list(self, client: AsyncClient, auth_headers: dict[str, str]) -> None:
        created = await client.post(
            "/subjects", json={"name": "Calculus", "color_hex": "#E86A5B"}, headers=auth_headers
        )
        assert created.status_code == 201

        listed = await client.get("/subjects", headers=auth_headers)
        assert [item["name"] for item in listed.json()] == ["Calculus"]

    async def test_duplicate_active_name_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str], subject: Subject
    ) -> None:
        response = await client.post("/subjects", json={"name": subject.name}, headers=auth_headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "subject_name_taken"

    async def test_archived_names_can_be_reused(
        self, client: AsyncClient, auth_headers: dict[str, str], subject: Subject
    ) -> None:
        await client.patch(
            f"/subjects/{subject.id}", json={"is_archived": True}, headers=auth_headers
        )
        response = await client.post("/subjects", json={"name": subject.name}, headers=auth_headers)
        assert response.status_code == 201

    async def test_archived_subjects_are_hidden_by_default(
        self, client: AsyncClient, auth_headers: dict[str, str], subject: Subject
    ) -> None:
        await client.patch(
            f"/subjects/{subject.id}", json={"is_archived": True}, headers=auth_headers
        )
        assert (await client.get("/subjects", headers=auth_headers)).json() == []
        with_archived = await client.get(
            "/subjects", params={"include_archived": True}, headers=auth_headers
        )
        assert len(with_archived.json()) == 1

    async def test_invalid_colour_is_rejected(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/subjects", json={"name": "Bad", "color_hex": "red"}, headers=auth_headers
        )
        assert response.status_code == 422

    async def test_reorder_assigns_positions(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        ids = []
        for name in ("A", "B", "C"):
            created = await client.post("/subjects", json={"name": name}, headers=auth_headers)
            ids.append(created.json()["id"])

        reordered = await client.post(
            "/subjects/reorder",
            json={"subject_ids": [ids[2], ids[0], ids[1]]},
            headers=auth_headers,
        )
        assert [item["id"] for item in reordered.json()] == [ids[2], ids[0], ids[1]]

    async def test_cannot_read_or_modify_another_users_subject(
        self, client: AsyncClient, auth_headers: dict[str, str], other_subject: Subject
    ) -> None:
        listed = await client.get("/subjects", headers=auth_headers)
        assert all(item["id"] != str(other_subject.id) for item in listed.json())

        response = await client.patch(
            f"/subjects/{other_subject.id}", json={"name": "Hijacked"}, headers=auth_headers
        )
        assert response.status_code == 404

    async def test_subjects_require_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/subjects")).status_code == 401


class TestPlanner:
    async def test_create_and_complete_a_task(
        self, client: AsyncClient, auth_headers: dict[str, str], subject: Subject
    ) -> None:
        created = await client.post(
            "/plans/2026-07-22/tasks",
            json={
                "title": "Review recursion",
                "subject_id": str(subject.id),
                "estimated_minutes": 45,
                "priority": "high",
            },
            headers=auth_headers,
        )
        assert created.status_code == 201
        task_id = created.json()["id"]

        completed = await client.patch(
            f"/tasks/{task_id}", json={"status": "done"}, headers=auth_headers
        )
        assert completed.json()["status"] == "done"
        assert completed.json()["completed_at"] is not None

    async def test_plan_is_created_on_demand(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get("/plans/2026-08-01", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["plan_date"] == "2026-08-01"
        assert response.json()["tasks"] == []

    async def test_carry_forward_defers_unfinished_tasks(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        await client.post(
            "/plans/2026-07-22/tasks", json={"title": "Unfinished"}, headers=auth_headers
        )
        done = await client.post(
            "/plans/2026-07-22/tasks", json={"title": "Finished"}, headers=auth_headers
        )
        await client.patch(
            f"/tasks/{done.json()['id']}", json={"status": "done"}, headers=auth_headers
        )

        carried = await client.post(
            "/plans/2026-07-22/carry-forward",
            json={"to_date": "2026-07-23"},
            headers=auth_headers,
        )
        assert [task["title"] for task in carried.json()] == ["Unfinished"]

        # The original is marked deferred rather than vanishing.
        source = await client.get("/plans/2026-07-22", headers=auth_headers)
        statuses = {task["title"]: task["status"] for task in source.json()["tasks"]}
        assert statuses == {"Unfinished": "deferred", "Finished": "done"}

    async def test_reflection_can_be_saved(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.put(
            "/plans/2026-07-22/reflection",
            json={"reflection": "Focus was better in the morning."},
            headers=auth_headers,
        )
        assert response.json()["reflection"] == "Focus was better in the morning."

    async def test_cannot_touch_another_users_task(
        self, client: AsyncClient, auth_headers: dict[str, str], other_auth_headers: dict[str, str]
    ) -> None:
        created = await client.post(
            "/plans/2026-07-22/tasks", json={"title": "Private"}, headers=auth_headers
        )
        task_id = created.json()["id"]

        assert (
            await client.patch(
                f"/tasks/{task_id}", json={"status": "done"}, headers=other_auth_headers
            )
        ).status_code == 404
        assert (
            await client.delete(f"/tasks/{task_id}", headers=other_auth_headers)
        ).status_code == 404

    async def test_cannot_attach_another_users_subject_to_a_task(
        self, client: AsyncClient, auth_headers: dict[str, str], other_subject: Subject
    ) -> None:
        response = await client.post(
            "/plans/2026-07-22/tasks",
            json={"title": "Sneaky", "subject_id": str(other_subject.id)},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_unknown_task_returns_not_found(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.patch(
            f"/tasks/{uuid.uuid4()}", json={"status": "done"}, headers=auth_headers
        )
        assert response.status_code == 404


class TestHealth:
    async def test_liveness(self, client: AsyncClient) -> None:
        assert (await client.get("/health/live")).json() == {"status": "ok"}

    async def test_readiness_checks_the_database(self, client: AsyncClient) -> None:
        response = await client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["checks"]["database"] == "ok"

    async def test_request_id_is_echoed(self, client: AsyncClient) -> None:
        response = await client.get("/health/live", headers={"X-Request-ID": "trace-me"})
        assert response.headers["X-Request-ID"] == "trace-me"


class TestSeed:
    async def test_seed_is_idempotent(self, db: AsyncSession) -> None:
        """Developers re-run seeding constantly; it must not multiply data."""
        from sqlalchemy import func, select

        from app.models.league import LeagueCategory
        from app.models.study import StudySession as SessionModel
        from app.seed import seed

        await seed(db)
        first_users = await db.scalar(select(func.count()).select_from(User))
        first_sessions = await db.scalar(select(func.count()).select_from(SessionModel))

        await seed(db)
        assert await db.scalar(select(func.count()).select_from(User)) == first_users
        assert await db.scalar(select(func.count()).select_from(SessionModel)) == first_sessions
        assert await db.scalar(select(func.count()).select_from(LeagueCategory)) == 7
