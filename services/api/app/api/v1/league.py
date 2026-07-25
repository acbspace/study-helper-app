"""League routes: join a season, see where you stand, and read exactly how you got there."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, LeagueServiceDep, UserTimezone
from app.core.clock import utc_now
from app.schemas.league import (
    BreakdownResponse,
    LeaderboardEntryResponse,
    LeagueStandingResponse,
    MissionResponse,
    SeasonHistoryResponse,
)

router = APIRouter(prefix="/league", tags=["league"])


@router.post("/enroll", response_model=LeagueStandingResponse, summary="Join the current season")
async def enroll(user: CurrentUser, league: LeagueServiceDep) -> LeagueStandingResponse:
    await league.ensure_enrollment(user)
    return LeagueStandingResponse.model_validate(await league.standing(user))


@router.get("/current", response_model=LeagueStandingResponse, summary="My current standing")
async def current(user: CurrentUser, league: LeagueServiceDep) -> LeagueStandingResponse:
    return LeagueStandingResponse.model_validate(await league.standing(user))


@router.get(
    "/leaderboard",
    response_model=list[LeaderboardEntryResponse],
    summary="My cohort leaderboard",
)
async def leaderboard(
    user: CurrentUser, league: LeagueServiceDep
) -> list[LeaderboardEntryResponse]:
    rows = await league.leaderboard(user)
    return [LeaderboardEntryResponse.model_validate(row) for row in rows]


@router.get("/breakdown", response_model=BreakdownResponse, summary="How a week was scored")
async def breakdown(
    user: CurrentUser,
    league: LeagueServiceDep,
    tz: UserTimezone,
    week_index: int | None = Query(default=None, ge=0, le=51),
) -> BreakdownResponse:
    if week_index is None:
        season = await league.active_season()
        today = utc_now().astimezone(tz).date()
        week_index = 0 if season is None else league.week_index_for(season, today)
    return BreakdownResponse.model_validate(await league.breakdown(user, week_index))


@router.get("/missions", response_model=list[MissionResponse], summary="Season missions")
async def missions(user: CurrentUser, league: LeagueServiceDep) -> list[MissionResponse]:
    rows = await league.missions(user)
    return [MissionResponse.model_validate(row) for row in rows]


@router.get("/history", response_model=list[SeasonHistoryResponse], summary="My past seasons")
async def history(user: CurrentUser, league: LeagueServiceDep) -> list[SeasonHistoryResponse]:
    rows = await league.history(user)
    return [SeasonHistoryResponse.model_validate(row) for row in rows]
