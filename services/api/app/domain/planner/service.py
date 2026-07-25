"""Daily planning: plans, tasks, deferral, and carry-forward.

`plan_date` is always the user's local date. The caller resolves "today" through the
statistics calendar helpers; this service never guesses a time zone.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.clock import ensure_utc
from app.core.errors import ErrorCode, NotFoundError
from app.models.enums import TaskPriority, TaskStatus
from app.models.planner import DailyPlan, Task
from app.models.study import Subject


class PlannerService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_plan(
        self, user_id: uuid.UUID, plan_date: date, *, create: bool = False
    ) -> DailyPlan | None:
        result = await self._db.execute(
            select(DailyPlan)
            .options(selectinload(DailyPlan.tasks))
            .where(DailyPlan.user_id == user_id, DailyPlan.plan_date == plan_date)
        )
        plan = result.scalar_one_or_none()
        if plan is not None or not create:
            return plan
        return await self._create_plan(user_id, plan_date)

    async def _create_plan(self, user_id: uuid.UUID, plan_date: date) -> DailyPlan:
        plan = DailyPlan(user_id=user_id, plan_date=plan_date)
        self._db.add(plan)
        try:
            await self._db.commit()
        except IntegrityError:
            # Another request created it first; the unique constraint did its job.
            await self._db.rollback()
            existing = await self.get_plan(user_id, plan_date)
            if existing is None:  # pragma: no cover - only if the row vanished mid-flight
                raise
            return existing
        await self._db.refresh(plan, attribute_names=["tasks"])
        return plan

    async def require_plan(self, user_id: uuid.UUID, plan_date: date) -> DailyPlan:
        plan = await self.get_plan(user_id, plan_date, create=True)
        assert plan is not None  # create=True always yields a plan
        return plan

    async def set_reflection(
        self, *, user_id: uuid.UUID, plan_date: date, reflection: str | None
    ) -> DailyPlan:
        plan = await self.require_plan(user_id, plan_date)
        plan.reflection = reflection
        await self._db.commit()
        await self._db.refresh(plan, attribute_names=["tasks"])
        return plan

    async def _require_subject(self, user_id: uuid.UUID, subject_id: uuid.UUID) -> Subject:
        result = await self._db.execute(
            select(Subject).where(Subject.id == subject_id, Subject.user_id == user_id)
        )
        subject = result.scalar_one_or_none()
        if subject is None:
            raise NotFoundError(ErrorCode.SUBJECT_NOT_FOUND, "Subject not found.")
        return subject

    async def get_owned_task(self, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
        """Fetch a task via its plan's owner — no cross-user access."""
        result = await self._db.execute(
            select(Task)
            .join(DailyPlan, Task.plan_id == DailyPlan.id)
            .where(Task.id == task_id, DailyPlan.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise NotFoundError(ErrorCode.TASK_NOT_FOUND, "Task not found.")
        return task

    async def create_task(
        self,
        *,
        user_id: uuid.UUID,
        plan_date: date,
        title: str,
        task_id: uuid.UUID | None = None,
        subject_id: uuid.UUID | None = None,
        estimated_minutes: int = 0,
        priority: TaskPriority = TaskPriority.NORMAL,
        sort_order: int | None = None,
    ) -> Task:
        plan = await self.require_plan(user_id, plan_date)
        if subject_id is not None:
            await self._require_subject(user_id, subject_id)

        if sort_order is None:
            result = await self._db.execute(
                select(func.coalesce(func.max(Task.sort_order), -1)).where(Task.plan_id == plan.id)
            )
            sort_order = int(result.scalar_one()) + 1

        task = Task(
            id=task_id or uuid.uuid4(),
            plan_id=plan.id,
            subject_id=subject_id,
            title=title.strip(),
            estimated_minutes=estimated_minutes,
            priority=priority.value,
            status=TaskStatus.PENDING.value,
            sort_order=sort_order,
        )
        self._db.add(task)
        await self._db.commit()
        await self._db.refresh(task)
        return task

    async def update_task(
        self,
        *,
        user_id: uuid.UUID,
        task_id: uuid.UUID,
        now: datetime,
        title: str | None = None,
        subject_id: uuid.UUID | None = None,
        estimated_minutes: int | None = None,
        priority: TaskPriority | None = None,
        status: TaskStatus | None = None,
        sort_order: int | None = None,
    ) -> Task:
        task = await self.get_owned_task(user_id, task_id)

        if title is not None:
            task.title = title.strip()
        if subject_id is not None:
            await self._require_subject(user_id, subject_id)
            task.subject_id = subject_id
        if estimated_minutes is not None:
            task.estimated_minutes = estimated_minutes
        if priority is not None:
            task.priority = priority.value
        if sort_order is not None:
            task.sort_order = sort_order
        if status is not None:
            task.status = status.value
            # The DB CHECK requires a timestamp on done tasks; keep them in lockstep.
            task.completed_at = ensure_utc(now) if status is TaskStatus.DONE else None

        await self._db.commit()
        await self._db.refresh(task)
        return task

    async def delete_task(self, *, user_id: uuid.UUID, task_id: uuid.UUID) -> None:
        task = await self.get_owned_task(user_id, task_id)
        await self._db.delete(task)
        await self._db.commit()

    async def carry_forward(
        self, *, user_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[Task]:
        """Copy unfinished tasks to another day.

        The original is marked `deferred` and linked to its successor, so "what did I keep
        postponing" stays answerable instead of silently disappearing.
        """
        source = await self.get_plan(user_id, from_date)
        if source is None:
            return []

        target = await self.require_plan(user_id, to_date)
        result = await self._db.execute(
            select(func.coalesce(func.max(Task.sort_order), -1)).where(Task.plan_id == target.id)
        )
        next_order = int(result.scalar_one()) + 1

        created: list[Task] = []
        for task in sorted(source.tasks, key=lambda item: item.sort_order):
            if task.status != TaskStatus.PENDING.value:
                continue
            copy = Task(
                id=uuid.uuid4(),
                plan_id=target.id,
                subject_id=task.subject_id,
                title=task.title,
                estimated_minutes=task.estimated_minutes,
                priority=task.priority,
                status=TaskStatus.PENDING.value,
                sort_order=next_order,
            )
            next_order += 1
            self._db.add(copy)
            task.status = TaskStatus.DEFERRED.value
            task.deferred_to_plan_id = target.id
            created.append(copy)

        await self._db.commit()
        for task in created:
            await self._db.refresh(task)
        return created
