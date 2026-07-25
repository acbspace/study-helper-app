"""Async engine and session lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine, enabling SQLite's foreign-key enforcement.

    SQLite disables foreign keys per connection by default, which would silently skip the
    referential invariants the schema relies on.
    """
    connect_args: dict[str, Any] = {}
    is_sqlite = settings.database_url.startswith("sqlite")
    if is_sqlite:
        connect_args["check_same_thread"] = False

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=not is_sqlite,
        connect_args=connect_args,
    )

    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_fks(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on failure."""
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
