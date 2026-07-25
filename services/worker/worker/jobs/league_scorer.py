"""Compute weekly League Points, and close a season when it ends.

Runs on a schedule rather than on write, because a week's score is only meaningful once the
week's activity exists, and because scoring every enrollment is a batch job by nature.

Safe to run repeatedly: the scoring run upserts by `(enrollment, week)`, so an extra
invocation recomputes the same numbers rather than adding to them. That matters — a cron that
cannot be retried is a cron that eventually loses a week.

Scoring the week that is still in progress is deliberate: users see points accrue live, and
the final value settles once the week closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.domain.league.service import LeagueService
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ScoringResult:
    season_scored: int
    week_index: int
    season_closed: bool


async def score_current_week(db: AsyncSession, *, now: datetime | None = None) -> ScoringResult:
    """Score the active season's current week, closing the season once it is over."""
    moment = now or datetime.now(UTC)
    today = moment.date()

    service = LeagueService(db)
    season = await service.active_season()
    if season is None:
        logger.info("league_scorer_skipped", reason="no_active_season")
        return ScoringResult(season_scored=0, week_index=0, season_closed=False)

    week_index = service.week_index_for(season, today)
    scored = await service.run_weekly_scoring(season=season, week_index=week_index)

    closed = False
    if today > season.ends_on:
        # The final week has been scored; now the ladder can be settled.
        await service.close_season(season)
        closed = True

    logger.info(
        "league_scorer_finished",
        season=str(season.id),
        week_index=week_index,
        scored=scored,
        closed=closed,
    )
    return ScoringResult(season_scored=scored, week_index=week_index, season_closed=closed)


async def run(ctx: dict[str, Any]) -> dict[str, Any]:
    """ARQ entry point."""
    factory = ctx["session_factory"]
    async with factory() as db:
        result = await score_current_week(db)
    return {
        "scored": result.season_scored,
        "week_index": result.week_index,
        "closed": result.season_closed,
    }
