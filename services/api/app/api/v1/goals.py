"""D-Day goal routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, GoalServiceDep
from app.domain.goals.service import GoalProgress
from app.schemas.goals import (
    CreateGoalRequest,
    GoalResponse,
    MilestoneResponse,
    UpdateGoalRequest,
)

router = APIRouter(prefix="/goals", tags=["goals"])


def _to_response(progress: GoalProgress) -> GoalResponse:
    goal = progress.goal
    return GoalResponse(
        id=goal.id,
        title=goal.title,
        target_date=goal.target_date,
        target_weekly_minutes=goal.target_weekly_minutes,
        subject_ids=list(goal.subject_ids),
        milestones=[MilestoneResponse.model_validate(item) for item in goal.milestones],
        description=goal.description,
        status=goal.status,
        completed_at=goal.completed_at,
        days_remaining=progress.days_remaining,
        is_overdue=progress.is_overdue,
        week_verified_minutes=progress.week_verified_minutes,
        weekly_progress=progress.weekly_progress,
        milestones_total=progress.milestones_total,
        milestones_done=progress.milestones_done,
    )


@router.get("", response_model=list[GoalResponse], summary="List goals")
async def list_goals(
    user: CurrentUser,
    goals: GoalServiceDep,
    include_finished: bool = Query(default=False),
) -> list[GoalResponse]:
    rows = await goals.list_for(user, include_finished=include_finished)
    return [_to_response(row) for row in rows]


@router.post(
    "",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a goal",
)
async def create_goal(
    payload: CreateGoalRequest, user: CurrentUser, goals: GoalServiceDep
) -> GoalResponse:
    progress = await goals.create(
        user=user,
        title=payload.title,
        target_date=payload.target_date,
        target_weekly_minutes=payload.target_weekly_minutes,
        subject_ids=payload.subject_ids,
        milestones=[milestone.model_dump() for milestone in payload.milestones],
        description=payload.description,
    )
    return _to_response(progress)


@router.get("/{goal_id}", response_model=GoalResponse, summary="Get a goal")
async def get_goal(goal_id: uuid.UUID, user: CurrentUser, goals: GoalServiceDep) -> GoalResponse:
    return _to_response(await goals.get_owned(user, goal_id))


@router.patch("/{goal_id}", response_model=GoalResponse, summary="Update a goal")
async def update_goal(
    goal_id: uuid.UUID,
    payload: UpdateGoalRequest,
    user: CurrentUser,
    goals: GoalServiceDep,
) -> GoalResponse:
    progress = await goals.update(
        user=user,
        goal_id=goal_id,
        title=payload.title,
        target_date=payload.target_date,
        clear_target_date=payload.clear_target_date,
        target_weekly_minutes=payload.target_weekly_minutes,
        subject_ids=payload.subject_ids,
        milestones=(
            None
            if payload.milestones is None
            else [milestone.model_dump() for milestone in payload.milestones]
        ),
        description=payload.description,
        status=payload.status,
    )
    return _to_response(progress)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a goal")
async def delete_goal(goal_id: uuid.UUID, user: CurrentUser, goals: GoalServiceDep) -> None:
    await goals.delete(user_id=user.id, goal_id=goal_id)
