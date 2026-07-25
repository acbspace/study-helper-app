"""League contracts."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.schemas.common import ResponseModel
from app.schemas.social import PublicUserResponse


class WeekPointsResponse(ResponseModel):
    week_index: int
    points: int


class LeagueStandingResponse(ResponseModel):
    season_id: uuid.UUID
    season_name: str
    starts_on: date
    ends_on: date
    status: str
    division_tier: int
    division_name: str
    cohort_id: uuid.UUID
    cohort_label: str
    category_name: str
    placement: str
    rank: int
    cohort_size: int
    total_points: int
    weeks: list[WeekPointsResponse]


class LeaderboardEntryResponse(ResponseModel):
    rank: int
    user: PublicUserResponse
    total_points: int
    placement: str
    is_me: bool


class ComponentResponse(ResponseModel):
    name: str
    points: int
    max_points: int
    detail: dict[str, Any]


class BreakdownResponse(ResponseModel):
    week_index: int
    week_start: date
    total_points: int
    scoring_version: str
    components: list[ComponentResponse]
    excluded_seconds: int
    exclusion_reasons: list[str]


class MissionResponse(ResponseModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str
    target: int
    reward_points: int
    progress: int
    completed: bool


class SeasonHistoryResponse(ResponseModel):
    season_id: uuid.UUID
    season_name: str
    division_name: str
    total_points: int
    final_rank: int | None = None
    outcome: str | None = None
