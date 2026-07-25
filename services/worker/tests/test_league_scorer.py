"""Weekly league scoring job behaviour."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest_asyncio
from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.domain.scoring.config import SCORING_CONFIG_V1
from app.models.enums import SeasonStatus
from app.models.league import (
    LeagueCategory,
    LeagueCohort,
    LeagueDivision,
    LeagueEnrollment,
    LeagueScore,
    LeagueSeason,
)
from app.models.user import User, UserProfile, UserSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.jobs.league_scorer import score_current_week

NOW = datetime(2026, 7, 22, 20, 0, tzinfo=UTC)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


@pytest_asyncio.fixture
async def db(tmp_path: object) -> AsyncIterator[AsyncSession]:
    settings = Settings(
        STUDY_ENV=Environment.TEST,
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path}/league.db",  # type: ignore[str-bytes-safe]
    )
    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_season(db: AsyncSession, *, starts_on: date, ends_on: date) -> LeagueSeason:
    category = LeagueCategory(slug="general_productivity", name="General", sort_order=0)
    season = LeagueSeason(
        name="Season",
        starts_on=starts_on,
        ends_on=ends_on,
        status=SeasonStatus.ACTIVE.value,
        scoring_config=SCORING_CONFIG_V1.to_dict(),
    )
    db.add_all([category, season])
    await db.flush()

    division = LeagueDivision(season_id=season.id, tier=0, name="Bronze")
    db.add(division)
    await db.flush()
    cohort = LeagueCohort(
        division_id=division.id, category_id=category.id, label="Bronze A", capacity=25
    )
    db.add(cohort)
    await db.flush()

    user = User(email="league@example.com", password_hash="x", auth_provider="email")
    user.profile = UserProfile(username="player", display_name="Player")
    user.settings = UserSettings(timezone="UTC")
    db.add(user)
    await db.flush()

    db.add(LeagueEnrollment(season_id=season.id, user_id=user.id, cohort_id=cohort.id))
    await db.commit()
    await db.refresh(season)
    return season


class TestLeagueScorer:
    async def test_no_active_season_is_a_noop(self, db: AsyncSession) -> None:
        result = await score_current_week(db, now=NOW)
        assert result.season_scored == 0
        assert result.season_closed is False

    async def test_scores_the_current_week(self, db: AsyncSession) -> None:
        starts_on = _monday(NOW.date())
        await _seed_season(db, starts_on=starts_on, ends_on=starts_on + timedelta(days=27))

        result = await score_current_week(db, now=NOW)
        assert result.season_scored == 1
        assert result.week_index == 0

        scores = list((await db.execute(select(LeagueScore))).scalars().all())
        assert len(scores) == 1
        # No activity was recorded, so the honest result is zero — not an error.
        assert scores[0].points_total == 0

    async def test_rerunning_upserts_rather_than_duplicating(self, db: AsyncSession) -> None:
        starts_on = _monday(NOW.date())
        await _seed_season(db, starts_on=starts_on, ends_on=starts_on + timedelta(days=27))

        await score_current_week(db, now=NOW)
        await score_current_week(db, now=NOW)

        scores = list((await db.execute(select(LeagueScore))).scalars().all())
        assert len(scores) == 1

    async def test_finished_season_is_closed(self, db: AsyncSession) -> None:
        starts_on = _monday(NOW.date()) - timedelta(days=28)
        season = await _seed_season(db, starts_on=starts_on, ends_on=starts_on + timedelta(days=27))

        result = await score_current_week(db, now=NOW)
        assert result.season_closed is True

        await db.refresh(season)
        assert season.status == SeasonStatus.CLOSED.value
        assert season.closed_at is not None

    async def test_week_index_tracks_the_calendar(self, db: AsyncSession) -> None:
        starts_on = _monday(NOW.date()) - timedelta(days=14)
        await _seed_season(db, starts_on=starts_on, ends_on=starts_on + timedelta(days=27))

        result = await score_current_week(db, now=NOW)
        assert result.week_index == 2
