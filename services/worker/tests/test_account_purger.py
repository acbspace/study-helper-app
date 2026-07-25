"""Deferred hard-deletion of accounts, and credential-table sweeping.

The grace period is the point of this job: deleting immediately would make an accidental or
coerced deletion unrecoverable, and would let someone erase the moderation history against
them by deleting their account. So the assertions here are as much about what the job leaves
alone as about what it removes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.models.study import Subject
from app.models.user import PasswordResetToken, RefreshToken, User, UserProfile, UserSettings
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.jobs.account_purger import DEFAULT_GRACE_DAYS, purge_deleted_accounts

NOW = datetime(2026, 7, 22, 3, 30, tzinfo=UTC)


@pytest_asyncio.fixture
async def db(tmp_path: object) -> AsyncIterator[AsyncSession]:
    settings = Settings(
        STUDY_ENV=Environment.TEST,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path}/purger.db",  # type: ignore[str-bytes-safe]
    )
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _make_user(
    db: AsyncSession, *, username: str, deleted_at: datetime | None = None
) -> User:
    user = User(
        email=f"{username}@example.com",
        password_hash="x",
        auth_provider="email",
        deleted_at=deleted_at,
        is_active=deleted_at is None,
    )
    user.profile = UserProfile(username=username, display_name=username.title())
    user.settings = UserSettings(timezone="UTC")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _count(db: AsyncSession, model: type) -> int:
    result = await db.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


class TestAccountPurge:
    async def test_removes_an_account_past_its_grace_period(self, db: AsyncSession) -> None:
        await _make_user(
            db, username="gone", deleted_at=NOW - timedelta(days=DEFAULT_GRACE_DAYS + 1)
        )
        result = await purge_deleted_accounts(db, now=NOW)
        assert result.accounts_purged == 1
        assert await _count(db, User) == 0

    async def test_keeps_an_account_still_inside_its_grace_period(self, db: AsyncSession) -> None:
        await _make_user(db, username="recent", deleted_at=NOW - timedelta(days=2))
        result = await purge_deleted_accounts(db, now=NOW)
        assert result.accounts_purged == 0
        assert await _count(db, User) == 1

    async def test_never_touches_a_live_account(self, db: AsyncSession) -> None:
        await _make_user(db, username="active")
        await purge_deleted_accounts(db, now=NOW)
        assert await _count(db, User) == 1

    async def test_cascades_to_the_account_s_own_data(self, db: AsyncSession) -> None:
        user = await _make_user(
            db, username="owner", deleted_at=NOW - timedelta(days=DEFAULT_GRACE_DAYS + 1)
        )
        db.add(Subject(user_id=user.id, name="Algorithms", color_hex="#4F6BED"))
        await db.commit()

        await purge_deleted_accounts(db, now=NOW)
        # A purge that leaves the rows behind has not actually deleted anything.
        assert await _count(db, Subject) == 0


class TestCredentialSweeping:
    async def test_removes_expired_reset_tokens(self, db: AsyncSession) -> None:
        user = await _make_user(db, username="resetter")
        db.add(
            PasswordResetToken(
                user_id=user.id, token_hash="a" * 64, expires_at=NOW - timedelta(hours=1)
            )
        )
        await db.commit()

        result = await purge_deleted_accounts(db, now=NOW)
        assert result.reset_tokens_removed == 1
        assert await _count(db, PasswordResetToken) == 0

    async def test_keeps_a_live_reset_token(self, db: AsyncSession) -> None:
        user = await _make_user(db, username="pending")
        db.add(
            PasswordResetToken(
                user_id=user.id, token_hash="b" * 64, expires_at=NOW + timedelta(minutes=10)
            )
        )
        await db.commit()

        await purge_deleted_accounts(db, now=NOW)
        assert await _count(db, PasswordResetToken) == 1

    async def test_keeps_recently_revoked_refresh_tokens(self, db: AsyncSession) -> None:
        import uuid

        user = await _make_user(db, username="rotator")
        db.add(
            RefreshToken(
                user_id=user.id,
                token_hash="c" * 64,
                family_id=uuid.uuid4(),
                expires_at=NOW + timedelta(days=30),
                revoked_at=NOW - timedelta(days=1),
            )
        )
        await db.commit()

        await purge_deleted_accounts(db, now=NOW)
        # Reuse detection needs the row to still exist: deleting it too early turns a
        # stolen-token replay into an ordinary "unknown token" instead of a breach signal.
        assert await _count(db, RefreshToken) == 1

    async def test_removes_long_revoked_refresh_tokens(self, db: AsyncSession) -> None:
        import uuid

        user = await _make_user(db, username="stale")
        db.add(
            RefreshToken(
                user_id=user.id,
                token_hash="d" * 64,
                family_id=uuid.uuid4(),
                expires_at=NOW + timedelta(days=30),
                revoked_at=NOW - timedelta(days=90),
            )
        )
        await db.commit()

        result = await purge_deleted_accounts(db, now=NOW)
        assert result.refresh_tokens_removed == 1
        assert await _count(db, RefreshToken) == 0

    async def test_is_a_no_op_on_an_empty_database(self, db: AsyncSession) -> None:
        result = await purge_deleted_accounts(db, now=NOW)
        assert result.accounts_purged == 0
        assert result.reset_tokens_removed == 0
        assert result.refresh_tokens_removed == 0
