"""Yearly insights (calendar heatmap + monthly totals) and personal data export."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.study import StudySession, Subject
from app.models.user import User


async def _add_session(
    db: AsyncSession,
    user: User,
    subject: Subject,
    *,
    started_at: datetime,
    minutes: int,
    integrity: str = "ok",
    source: str = "timer",
) -> None:
    db.add(
        StudySession(
            id=uuid.uuid4(),
            user_id=user.id,
            subject_id=subject.id,
            source=source,
            status="completed",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=minutes),
            duration_seconds=minutes * 60,
            integrity_status=integrity,
        )
    )


class TestYearlyInsights:
    async def test_heatmap_and_months(
        self, client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession, user: User
    ) -> None:
        subject = Subject(user_id=user.id, name="History", color_hex="#4F6BED")
        db.add(subject)
        await db.flush()

        # Two sessions on the same March day (they should merge in the heatmap) and one in June.
        march = datetime(2026, 3, 10, 8, 0, tzinfo=UTC)
        june = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        await _add_session(db, user, subject, started_at=march, minutes=60)
        await _add_session(db, user, subject, started_at=march + timedelta(hours=3), minutes=30)
        await _add_session(db, user, subject, started_at=june, minutes=45)
        await db.commit()

        response = await client.get(
            "/statistics/yearly", params={"year": 2026}, headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["year"] == 2026
        assert len(body["heatmap"]) == 365
        assert body["active_days"] == 2
        assert body["session_count"] == 3

        by_day = {entry["day"]: entry["verified_seconds"] for entry in body["heatmap"]}
        # The two March sessions merged into one day's total (90 minutes).
        assert by_day["2026-03-10"] == 90 * 60

        by_month = {month["month"]: month for month in body["months"]}
        assert len(body["months"]) == 12
        assert by_month["2026-03"]["verified_seconds"] == 90 * 60
        assert by_month["2026-03"]["active_days"] == 1
        assert by_month["2026-06"]["session_count"] == 1
        assert by_month["2026-01"]["verified_seconds"] == 0

    async def test_longest_streak_counts_consecutive_days(
        self, client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession, user: User
    ) -> None:
        subject = Subject(user_id=user.id, name="Streaky", color_hex="#4F6BED")
        db.add(subject)
        await db.flush()
        base = datetime(2026, 2, 2, 8, 0, tzinfo=UTC)  # a Monday
        for offset in (0, 1, 2, 5):  # a 3-day run, then a gap, then one more
            await _add_session(
                db, user, subject, started_at=base + timedelta(days=offset), minutes=30
            )
        await db.commit()

        response = await client.get(
            "/statistics/yearly", params={"year": 2026}, headers=auth_headers
        )
        assert response.json()["longest_streak_days"] == 3

    async def test_manual_time_is_not_verified(
        self, client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession, user: User
    ) -> None:
        subject = Subject(user_id=user.id, name="Manual", color_hex="#4F6BED")
        db.add(subject)
        await db.flush()
        when = datetime(2026, 4, 4, 8, 0, tzinfo=UTC)
        await _add_session(db, user, subject, started_at=when, minutes=60, source="manual")
        await db.commit()

        body = (
            await client.get("/statistics/yearly", params={"year": 2026}, headers=auth_headers)
        ).json()
        by_day = {entry["day"]: entry["verified_seconds"] for entry in body["heatmap"]}
        assert by_day["2026-04-04"] == 0  # manual time is not verified
        assert body["manual_seconds"] == 60 * 60


class TestDataExport:
    async def test_export_bundles_the_users_own_data(
        self, client: AsyncClient, auth_headers: dict[str, str], user: User
    ) -> None:
        await client.post("/subjects", json={"name": "Calculus"}, headers=auth_headers)
        await client.post("/goals", json={"title": "Finish the course"}, headers=auth_headers)
        await client.post(
            "/plans/2026-07-24/tasks", json={"title": "Chapter 3"}, headers=auth_headers
        )

        response = await client.get("/me/export", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["export_version"] == "1"
        assert body["account"]["email"] == user.email
        assert body["account"]["profile"]["username"] == user.profile.username
        assert [s["name"] for s in body["subjects"]] == ["Calculus"]
        assert [g["title"] for g in body["goals"]] == ["Finish the course"]
        assert body["plans"][0]["tasks"][0]["title"] == "Chapter 3"

    async def test_export_is_scoped_to_the_caller(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        await client.post("/subjects", json={"name": "Private"}, headers=auth_headers)

        others = await client.get("/me/export", headers=other_auth_headers)
        assert others.json()["subjects"] == []

    async def test_export_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/me/export")).status_code == 401
        assert (await client.get("/statistics/yearly")).status_code == 401
