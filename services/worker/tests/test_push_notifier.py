"""Push-notifier worker job wiring.

The delivery logic itself is covered by the API suite (`test_push.py`); here we only prove
the ARQ job opens a session and runs cleanly. With no pending notifications it never reaches
the real Expo sender, so this stays fully offline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from sqlalchemy.ext.asyncio import async_sessionmaker

from worker.jobs.push_notifier import run


@pytest_asyncio.fixture
async def session_factory(tmp_path: object) -> AsyncIterator[async_sessionmaker]:
    settings = Settings(
        STUDY_ENV=Environment.TEST,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path}/push.db",  # type: ignore[str-bytes-safe]
    )
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


class TestPushNotifierJob:
    async def test_noop_when_nothing_pending(self, session_factory: async_sessionmaker) -> None:
        result = await run({"session_factory": session_factory})
        assert result == {"considered": 0, "delivered": 0}
