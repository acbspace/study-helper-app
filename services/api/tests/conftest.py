"""Test fixtures.

Each test gets an isolated database. SQLite (in a temp file, so multiple connections in
one test see the same data) is the default; set TEST_DATABASE_URL to run the identical
suite against PostgreSQL, which CI does on every push (ADR-0003).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.domain.sessions.integrity import IntegrityThresholds
from app.domain.sessions.service import StudySessionService
from app.main import create_app
from app.models.study import Subject
from app.models.user import User, UserProfile, UserSettings

FIXED_NOW = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Per-test settings pointing at a throwaway database."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        # One schema-per-test is unnecessary on PostgreSQL: tables are dropped and
        # recreated between tests by the engine fixture.
        database_url = url
    else:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"

    return Settings(
        STUDY_ENV=Environment.TEST,
        DATABASE_URL=database_url,
        # 32+ chars: matches the production minimum so tests exercise a realistic key.
        JWT_SECRET="test-secret-never-used-outside-the-test-suite-0123456789",
        RATE_LIMIT_ENABLED=False,
        DEVICE_HASH_SALT="test-salt",
    )


@pytest_asyncio.fixture
async def session_factory(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield create_session_factory(engine)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    """HTTP client wired to the app without running a server or the real lifespan."""
    app = create_app(settings)
    app.state.session_factory = session_factory
    app.state.redis = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as http:
        yield http


@pytest_asyncio.fixture
async def user(db: AsyncSession) -> User:
    """A registered user in Asia/Seoul (UTC+9) â€” a non-UTC zone by design, so time-zone
    bugs surface in ordinary tests rather than only in dedicated ones."""
    from app.core.security import hash_password

    record = User(
        email="student@example.com",
        password_hash=hash_password("password123"),
        auth_provider="email",
    )
    record.profile = UserProfile(
        username="student", display_name="Student", study_category="software_engineering"
    )
    record.settings = UserSettings(
        timezone="Asia/Seoul",
        daily_goal_minutes=120,
        weekly_goal_minutes=600,
        scheduled_study_days=0b0011111,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record, attribute_names=["profile", "settings"])
    return record


@pytest_asyncio.fixture
async def other_user(db: AsyncSession) -> User:
    """A second account, used to prove cross-user access is impossible."""
    from app.core.security import hash_password

    record = User(
        email="rival@example.com",
        password_hash=hash_password("password123"),
        auth_provider="email",
    )
    record.profile = UserProfile(
        username="rival", display_name="Rival", study_category="university"
    )
    record.settings = UserSettings(timezone="UTC")
    db.add(record)
    await db.commit()
    await db.refresh(record, attribute_names=["profile", "settings"])
    return record


@pytest_asyncio.fixture
async def subject(db: AsyncSession, user: User) -> Subject:
    record = Subject(user_id=user.id, name="Algorithms", color_hex="#4F6BED", sort_order=0)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@pytest_asyncio.fixture
async def other_subject(db: AsyncSession, other_user: User) -> Subject:
    record = Subject(user_id=other_user.id, name="Chemistry", color_hex="#37B27A")
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@pytest.fixture
def sessions_service(db: AsyncSession) -> StudySessionService:
    return StudySessionService(db, IntegrityThresholds())


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def other_auth_headers(client: AsyncClient, other_user: User) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"email": other_user.email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
