"""Data export: a user's own data, handed back to them.

A privacy right, not a feature: the export is a plain, self-describing JSON document a user can
read, keep, or take elsewhere. It includes everything *they* created — profile, subjects,
sessions, plans, goals — and deliberately excludes other people's data and server-internal
fields (integrity internals, other users' ids), because "my data" means mine, not everyone I
ever interacted with.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.models.planner import DailyPlan, Task
from app.models.study import StudyGoal, StudySession, Subject
from app.models.user import User

EXPORT_VERSION = "1"


class ExportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def export(self, user: User) -> dict[str, Any]:
        return {
            "export_version": EXPORT_VERSION,
            "generated_at": utc_now().isoformat(),
            "account": {
                "email": user.email,
                "profile": _profile(user),
                "settings": _settings(user),
            },
            "subjects": await self._subjects(user.id),
            "sessions": await self._sessions(user.id),
            "plans": await self._plans(user.id),
            "goals": await self._goals(user.id),
        }

    async def _subjects(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(Subject).where(Subject.user_id == user_id).order_by(Subject.sort_order)
        )
        return [
            {
                "id": str(subject.id),
                "name": subject.name,
                "color_hex": subject.color_hex,
                "is_archived": subject.is_archived,
            }
            for subject in result.scalars().all()
        ]

    async def _sessions(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(StudySession)
            .where(StudySession.user_id == user_id)
            .order_by(StudySession.started_at)
        )
        return [
            {
                "id": str(session.id),
                "subject_id": str(session.subject_id),
                "source": session.source,
                "status": session.status,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "duration_seconds": session.duration_seconds,
                "note": session.note,
                "went_as_planned": session.went_as_planned,
                # The user is told when time is excluded, so the export is honest about it too.
                "integrity_status": session.integrity_status,
            }
            for session in result.scalars().all()
        ]

    async def _plans(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(DailyPlan).where(DailyPlan.user_id == user_id).order_by(DailyPlan.plan_date)
        )
        plans = list(result.scalars().all())
        if not plans:
            return []

        tasks_by_plan: dict[uuid.UUID, list[dict[str, Any]]] = {}
        task_rows = await self._db.execute(
            select(Task)
            .where(Task.plan_id.in_([plan.id for plan in plans]))
            .order_by(Task.sort_order)
        )
        for task in task_rows.scalars().all():
            tasks_by_plan.setdefault(task.plan_id, []).append(
                {
                    "title": task.title,
                    "subject_id": str(task.subject_id) if task.subject_id else None,
                    "estimated_minutes": task.estimated_minutes,
                    "priority": task.priority,
                    "status": task.status,
                }
            )

        return [
            {
                "date": plan.plan_date.isoformat(),
                "reflection": plan.reflection,
                "tasks": tasks_by_plan.get(plan.id, []),
            }
            for plan in plans
        ]

    async def _goals(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        result = await self._db.execute(
            select(StudyGoal).where(StudyGoal.user_id == user_id).order_by(StudyGoal.created_at)
        )
        return [
            {
                "title": goal.title,
                "target_date": goal.target_date.isoformat() if goal.target_date else None,
                "target_weekly_minutes": goal.target_weekly_minutes,
                "milestones": goal.milestones,
                "description": goal.description,
                "status": goal.status,
            }
            for goal in result.scalars().all()
        ]


def _profile(user: User) -> dict[str, Any]:
    profile = user.profile
    return {
        "username": profile.username,
        "display_name": profile.display_name,
        "country_code": profile.country_code,
        "study_category": profile.study_category,
        "bio": profile.bio,
    }


def _settings(user: User) -> dict[str, Any]:
    settings = user.settings
    return {
        "timezone": settings.timezone,
        "language": settings.language,
        "daily_goal_minutes": settings.daily_goal_minutes,
        "weekly_goal_minutes": settings.weekly_goal_minutes,
        "scheduled_study_days": settings.scheduled_study_days,
    }
