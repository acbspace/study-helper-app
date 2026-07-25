"""Stale-session reaper behaviour."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.clock import ensure_utc
from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.models.enums import IntegrityStatus, SessionEventType, SessionStatus
from app.models.platform import AuditLog
from app.models.study import StudySession, StudySessionEvent, Subject
from app.models.user import User, UserProfile, UserSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.jobs.session_reaper import reap_stale_sessions

NOW = datetime(2026, 7, 22, 20, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db(tmp_path: object) -> AsyncIterator[AsyncSession]:
    settings = Settings(
        STUDY_ENV=Environment.TEST,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path}/reaper.db",  # type: ignore[str-bytes-safe]
    )
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def subject(db: AsyncSession) -> Subject:
    user = User(email="reaper@example.com", password_hash="x", auth_provider="email")
    user.profile = UserProfile(username="reaper", display_name="Reaper")
    user.settings = UserSettings(timezone="UTC")
    db.add(user)
    await db.flush()

    record = Subject(user_id=user.id, name="Algorithms", color_hex="#4F6BED")
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def make_running_session(
    db: AsyncSession, subject: Subject, *, started_at: datetime
) -> StudySession:
    session = StudySession(
        id=uuid.uuid4(),
        user_id=subject.user_id,
        subject_id=subject.id,
        status=SessionStatus.ACTIVE.value,
        started_at=started_at,
        integrity_reasons=[],
    )
    session.events.append(
        StudySessionEvent(
            id=uuid.uuid4(),
            sequence=1,
            event_type=SessionEventType.START.value,
            occurred_at=started_at,
            server_received_at=started_at,
            payload={},
        )
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


class TestReaper:
    async def test_abandoned_session_is_closed(self, db: AsyncSession, subject: Subject) -> None:
        session = await make_running_session(db, subject, started_at=NOW - timedelta(hours=20))
        result = await reap_stale_sessions(db, now=NOW, max_age_hours=12)

        assert result.closed == 1
        await db.refresh(session)
        assert session.status == SessionStatus.COMPLETED.value

    async def test_closed_at_last_activity_not_at_discovery_time(
        self, db: AsyncSession, subject: Subject
    ) -> None:
        """A phone that died at 2am must not be credited with study time until 8pm."""
        started = NOW - timedelta(hours=20)
        session = await make_running_session(db, subject, started_at=started)
        await reap_stale_sessions(db, now=NOW, max_age_hours=12)

        await db.refresh(session)
        assert session.ended_at is not None
        assert session.duration_seconds == 0  # last event *is* the start event
        # SQLite returns naive datetimes; normalise the way the domain layer does.
        assert abs((ensure_utc(session.ended_at) - started).total_seconds()) < 1

    async def test_recent_session_is_left_alone(self, db: AsyncSession, subject: Subject) -> None:
        session = await make_running_session(db, subject, started_at=NOW - timedelta(hours=2))
        result = await reap_stale_sessions(db, now=NOW, max_age_hours=12)

        assert result.closed == 0
        await db.refresh(session)
        assert session.status == SessionStatus.ACTIVE.value

    async def test_old_session_with_recent_activity_survives(
        self, db: AsyncSession, subject: Subject
    ) -> None:
        """Started this morning, paused and resumed an hour ago: still a live session."""
        session = await make_running_session(db, subject, started_at=NOW - timedelta(hours=20))
        db.add(
            StudySessionEvent(
                id=uuid.uuid4(),
                session_id=session.id,
                sequence=2,
                event_type=SessionEventType.PAUSE.value,
                occurred_at=NOW - timedelta(hours=1),
                server_received_at=NOW - timedelta(hours=1),
                payload={},
            )
        )
        await db.commit()

        result = await reap_stale_sessions(db, now=NOW, max_age_hours=12)
        assert result.closed == 0

    async def test_closed_session_is_flagged_and_audited(
        self, db: AsyncSession, subject: Subject
    ) -> None:
        await make_running_session(db, subject, started_at=NOW - timedelta(hours=20))
        await reap_stale_sessions(db, now=NOW, max_age_hours=12)

        entries = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "session.auto_closed")))
            .scalars()
            .all()
        )
        assert len(entries) == 1
        assert entries[0].actor_type == "system"

        session = (await db.execute(select(StudySession))).scalar_one()
        assert session.integrity_status == IntegrityStatus.FLAGGED.value

    async def test_running_twice_closes_nothing_the_second_time(
        self, db: AsyncSession, subject: Subject
    ) -> None:
        """Jobs must be safe to retry."""
        await make_running_session(db, subject, started_at=NOW - timedelta(hours=20))
        first = await reap_stale_sessions(db, now=NOW, max_age_hours=12)
        second = await reap_stale_sessions(db, now=NOW, max_age_hours=12)

        assert first.closed == 1
        assert second.closed == 0

    async def test_closing_frees_the_slot_for_a_new_session(
        self, db: AsyncSession, subject: Subject
    ) -> None:
        """The whole point: a forgotten timer must not lock the user out tomorrow."""
        await make_running_session(db, subject, started_at=NOW - timedelta(hours=20))
        await reap_stale_sessions(db, now=NOW, max_age_hours=12)

        fresh = await make_running_session(db, subject, started_at=NOW)
        assert fresh.status == SessionStatus.ACTIVE.value


@pytest.mark.parametrize("max_age", [6.0, 12.0, 24.0])
async def test_threshold_is_configurable(
    db: AsyncSession, subject: Subject, max_age: float
) -> None:
    await make_running_session(db, subject, started_at=NOW - timedelta(hours=13))
    result = await reap_stale_sessions(db, now=NOW, max_age_hours=max_age)
    assert result.closed == (1 if max_age < 13 else 0)
