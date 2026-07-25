"""Daily planner and task routes."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, PlannerServiceDep, UserTimezone
from app.core.clock import utc_now
from app.domain.statistics.calendar import local_date_of
from app.schemas.planner import (
    CarryForwardRequest,
    CreateTaskRequest,
    DailyPlanResponse,
    ReflectionRequest,
    TaskResponse,
    UpdateTaskRequest,
)

router = APIRouter(tags=["planner"])


@router.get("/plans/today", response_model=DailyPlanResponse, summary="Today's plan")
async def get_today_plan(
    user: CurrentUser, planner: PlannerServiceDep, tz: UserTimezone
) -> DailyPlanResponse:
    plan = await planner.require_plan(user.id, local_date_of(utc_now(), tz))
    return DailyPlanResponse.model_validate(plan)


@router.get("/plans/{plan_date}", response_model=DailyPlanResponse, summary="Plan for a date")
async def get_plan(
    plan_date: date, user: CurrentUser, planner: PlannerServiceDep
) -> DailyPlanResponse:
    plan = await planner.require_plan(user.id, plan_date)
    return DailyPlanResponse.model_validate(plan)


@router.put(
    "/plans/{plan_date}/reflection",
    response_model=DailyPlanResponse,
    summary="Write a daily reflection",
)
async def set_reflection(
    plan_date: date,
    payload: ReflectionRequest,
    user: CurrentUser,
    planner: PlannerServiceDep,
) -> DailyPlanResponse:
    plan = await planner.set_reflection(
        user_id=user.id, plan_date=plan_date, reflection=payload.reflection
    )
    return DailyPlanResponse.model_validate(plan)


@router.post(
    "/plans/{plan_date}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a task",
)
async def create_task(
    plan_date: date,
    payload: CreateTaskRequest,
    user: CurrentUser,
    planner: PlannerServiceDep,
) -> TaskResponse:
    task = await planner.create_task(
        user_id=user.id,
        plan_date=plan_date,
        task_id=payload.task_id,
        title=payload.title,
        subject_id=payload.subject_id,
        estimated_minutes=payload.estimated_minutes,
        priority=payload.priority,
        sort_order=payload.sort_order,
    )
    return TaskResponse.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse, summary="Update a task")
async def update_task(
    task_id: uuid.UUID,
    payload: UpdateTaskRequest,
    user: CurrentUser,
    planner: PlannerServiceDep,
) -> TaskResponse:
    task = await planner.update_task(
        user_id=user.id,
        task_id=task_id,
        title=payload.title,
        subject_id=payload.subject_id,
        estimated_minutes=payload.estimated_minutes,
        priority=payload.priority,
        status=payload.status,
        sort_order=payload.sort_order,
        now=utc_now(),
    )
    return TaskResponse.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a task")
async def delete_task(task_id: uuid.UUID, user: CurrentUser, planner: PlannerServiceDep) -> None:
    await planner.delete_task(user_id=user.id, task_id=task_id)


@router.post(
    "/plans/{plan_date}/carry-forward",
    response_model=list[TaskResponse],
    summary="Copy unfinished tasks to another day",
)
async def carry_forward(
    plan_date: date,
    payload: CarryForwardRequest,
    user: CurrentUser,
    planner: PlannerServiceDep,
) -> list[TaskResponse]:
    tasks = await planner.carry_forward(
        user_id=user.id, from_date=plan_date, to_date=payload.to_date
    )
    return [TaskResponse.model_validate(task) for task in tasks]
