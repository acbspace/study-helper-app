"""Statistics, with an emphasis on time-zone correctness and verified/manual separation."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.statistics.service import StatisticsService
from app.models.enums import IntegrityStatus, SessionSource, SessionStatus
from app.models.study import StudySession, Subject
from app.models.user import User

SEOUL = ZoneInfo("Asia/Seoul")  # UTC+9


async def add_session(
    db: AsyncSession,
    user: User,
    subject: Subject,
    *,
    started_at: datetime,
    minutes: int,
    source: SessionSource = SessionSource.TIMER,
    integrity: IntegrityStatus = IntegrityStatus.OK,
) -> StudySession:
    session = StudySession(
        id=uuid.uuid4(),
        user_id=user.id,
        subject_id=subject.id,
        source=source.value,
        status=SessionStatus.COMPLETED.value,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=minutes),
        duration_seconds=minutes * 60,
        integrity_status=integrity.value,
        integrity_reasons=[],
    )
    db.add(session)
    await db.commit()
    return session


class TestTimezoneAggregation:
    async def test_session_is_attributed_to_the_users_local_day(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        """22:00 UTC on the 22nd is 07:00 Seoul on the 23rd — it counts for the 23rd."""
        await add_session(
            db, user, subject, started_at=datetime(2026, 7, 22, 22, 0, tzinfo=UTC), minutes=60
        )
        statistics = StatisticsService(db)

        on_22nd = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        on_23rd = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 23),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert on_22nd.verified_seconds == 0
        assert on_23rd.verified_seconds == 3600

    async def test_the_same_session_lands_on_different_days_in_different_zones(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        await add_session(
            db, user, subject, started_at=datetime(2026, 7, 22, 22, 0, tzinfo=UTC), minutes=60
        )
        statistics = StatisticsService(db)

        seoul = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 23),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        utc = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 22),
            tz=ZoneInfo("UTC"),
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert seoul.verified_seconds == 3600
        assert utc.verified_seconds == 3600

    async def test_weekly_summary_buckets_days_in_local_time(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        # 15:30 UTC Sunday = 00:30 Monday in Seoul: belongs to the *next* week.
        await add_session(
            db, user, subject, started_at=datetime(2026, 7, 19, 15, 30, tzinfo=UTC), minutes=30
        )
        statistics = StatisticsService(db)
        week = await statistics.weekly_summary(
            user_id=user.id,
            anchor_day=date(2026, 7, 22),
            tz=SEOUL,
            daily_goal_minutes=120,
            weekly_goal_minutes=600,
            scheduled_days_mask=0b0011111,
        )
        assert week.week_start == date(2026, 7, 20)
        monday = next(day for day in week.days if day.day == date(2026, 7, 20))
        assert monday.verified_seconds == 30 * 60


class TestVerifiedVersusManual:
    async def test_manual_and_verified_time_are_reported_separately(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        base = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)  # 11:00 Seoul
        await add_session(db, user, subject, started_at=base, minutes=60)
        await add_session(
            db,
            user,
            subject,
            started_at=base + timedelta(hours=3),
            minutes=90,
            source=SessionSource.MANUAL,
            integrity=IntegrityStatus.EXCLUDED,
        )
        statistics = StatisticsService(db)
        summary = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert summary.verified_seconds == 60 * 60
        assert summary.manual_seconds == 90 * 60
        assert summary.total_seconds == 150 * 60

    async def test_flagged_time_is_counted_as_excluded(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        await add_session(
            db,
            user,
            subject,
            started_at=datetime(2026, 7, 22, 2, 0, tzinfo=UTC),
            minutes=120,
            integrity=IntegrityStatus.FLAGGED,
        )
        statistics = StatisticsService(db)
        summary = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert summary.verified_seconds == 0
        assert summary.excluded_seconds == 120 * 60

    async def test_only_verified_time_counts_toward_the_goal(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        """Otherwise the goal — and the league — could be met by typing numbers in."""
        await add_session(
            db,
            user,
            subject,
            started_at=datetime(2026, 7, 22, 2, 0, tzinfo=UTC),
            minutes=300,
            source=SessionSource.MANUAL,
            integrity=IntegrityStatus.EXCLUDED,
        )
        statistics = StatisticsService(db)
        summary = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert summary.goal_progress == 0.0


class TestSubjectBreakdown:
    async def test_subjects_are_ranked_by_total_time(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        second = Subject(user_id=user.id, name="Databases", color_hex="#37B27A")
        db.add(second)
        await db.commit()
        await db.refresh(second)

        base = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)
        await add_session(db, user, subject, started_at=base, minutes=30)
        await add_session(db, user, second, started_at=base + timedelta(hours=2), minutes=90)

        statistics = StatisticsService(db)
        summary = await statistics.daily_summary(
            user_id=user.id,
            day=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert [item.name for item in summary.subjects] == ["Databases", "Algorithms"]
        assert summary.subjects[0].verified_seconds == 90 * 60


class TestStreaks:
    async def test_consecutive_goal_days_build_a_streak(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        # 2026-07-20 Mon, 21 Tue, 22 Wed — all scheduled weekdays.
        for day_offset in range(3):
            await add_session(
                db,
                user,
                subject,
                started_at=datetime(2026, 7, 20 + day_offset, 2, 0, tzinfo=UTC),
                minutes=120,
            )
        statistics = StatisticsService(db)
        streak = await statistics.current_streak(
            user_id=user.id,
            today=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert streak == 3

    async def test_scheduled_rest_days_do_not_break_a_streak(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        """Friday and Monday with a weekend between is still a 2-day streak."""
        for day in (24, 27):  # Fri 2026-07-24, Mon 2026-07-27
            await add_session(
                db, user, subject, started_at=datetime(2026, 7, day, 2, 0, tzinfo=UTC), minutes=120
            )
        statistics = StatisticsService(db)
        streak = await statistics.current_streak(
            user_id=user.id,
            today=date(2026, 7, 27),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert streak == 2

    async def test_missing_a_scheduled_day_breaks_the_streak(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        await add_session(
            db, user, subject, started_at=datetime(2026, 7, 20, 2, 0, tzinfo=UTC), minutes=120
        )
        # Nothing on Tuesday the 21st.
        await add_session(
            db, user, subject, started_at=datetime(2026, 7, 22, 2, 0, tzinfo=UTC), minutes=120
        )
        statistics = StatisticsService(db)
        streak = await statistics.current_streak(
            user_id=user.id,
            today=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert streak == 1

    async def test_an_unfinished_today_does_not_reset_yesterdays_streak(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        """A streak must not read zero every morning before you have studied."""
        await add_session(
            db, user, subject, started_at=datetime(2026, 7, 21, 2, 0, tzinfo=UTC), minutes=120
        )
        statistics = StatisticsService(db)
        streak = await statistics.current_streak(
            user_id=user.id,
            today=date(2026, 7, 22),
            tz=SEOUL,
            goal_minutes=120,
            scheduled_days_mask=0b0011111,
        )
        assert streak == 1


class TestWeeklyGoalMetrics:
    async def test_goal_completion_rate_uses_scheduled_days_only(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        for day in (20, 21):  # Mon, Tue of a Mon–Fri schedule
            await add_session(
                db, user, subject, started_at=datetime(2026, 7, day, 2, 0, tzinfo=UTC), minutes=120
            )
        statistics = StatisticsService(db)
        week = await statistics.weekly_summary(
            user_id=user.id,
            anchor_day=date(2026, 7, 22),
            tz=SEOUL,
            daily_goal_minutes=120,
            weekly_goal_minutes=600,
            scheduled_days_mask=0b0011111,
        )
        assert week.scheduled_days == 5
        assert week.scheduled_days_met == 2
        assert week.goal_completion_rate == 0.4

    async def test_average_session_length_is_reported(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        base = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)
        await add_session(db, user, subject, started_at=base, minutes=30)
        await add_session(db, user, subject, started_at=base + timedelta(hours=3), minutes=90)
        statistics = StatisticsService(db)
        week = await statistics.weekly_summary(
            user_id=user.id,
            anchor_day=date(2026, 7, 22),
            tz=SEOUL,
            daily_goal_minutes=120,
            weekly_goal_minutes=600,
            scheduled_days_mask=0b0011111,
        )
        assert week.average_session_seconds == 60 * 60
        assert week.session_count == 2


class TestStatisticsEndpoints:
    async def test_summary_endpoint_returns_today_and_this_week(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(
            "/statistics/summary", params={"date": "2026-07-22"}, headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["today"]["date"] == "2026-07-22"
        # The response always names the zone it was computed in.
        assert body["today"]["timezone"] == "Asia/Seoul"
        assert body["week"]["week_start"] == "2026-07-20"
        assert len(body["week"]["days"]) == 7

    async def test_summary_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.get("/statistics/summary")).status_code == 401

    async def test_statistics_are_scoped_to_the_caller(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db: AsyncSession,
        other_user: User,
        other_subject: Subject,
    ) -> None:
        """Another user's study time must never appear in my totals."""
        await add_session(
            db,
            other_user,
            other_subject,
            started_at=datetime(2026, 7, 22, 2, 0, tzinfo=UTC),
            minutes=240,
        )
        response = await client.get(
            "/statistics/summary", params={"date": "2026-07-22"}, headers=auth_headers
        )
        assert response.json()["today"]["verified_seconds"] == 0
