"""Subject CRUD, ordering, and archival.

Subjects are never hard-deleted: study sessions reference them and history must stay
readable. Archiving hides a subject from pickers while keeping past statistics intact.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ErrorCode, NotFoundError
from app.models.study import Subject


class SubjectService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_user(
        self, user_id: uuid.UUID, *, include_archived: bool = False
    ) -> list[Subject]:
        query = select(Subject).where(Subject.user_id == user_id)
        if not include_archived:
            query = query.where(Subject.is_archived.is_(False))
        result = await self._db.execute(query.order_by(Subject.sort_order, Subject.name))
        return list(result.scalars().all())

    async def get_owned(self, user_id: uuid.UUID, subject_id: uuid.UUID) -> Subject:
        """Ownership is part of the lookup, so another user's subject is simply not found."""
        result = await self._db.execute(
            select(Subject).where(Subject.id == subject_id, Subject.user_id == user_id)
        )
        subject = result.scalar_one_or_none()
        if subject is None:
            raise NotFoundError(ErrorCode.SUBJECT_NOT_FOUND, "Subject not found.")
        return subject

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        color_hex: str,
        sort_order: int | None = None,
    ) -> Subject:
        if sort_order is None:
            result = await self._db.execute(
                select(func.coalesce(func.max(Subject.sort_order), -1)).where(
                    Subject.user_id == user_id
                )
            )
            sort_order = int(result.scalar_one()) + 1

        subject = Subject(
            user_id=user_id,
            name=name.strip(),
            color_hex=color_hex,
            sort_order=sort_order,
            is_archived=False,
        )
        self._db.add(subject)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError(
                ErrorCode.SUBJECT_NAME_TAKEN,
                "You already have an active subject with that name.",
                name=name,
            ) from exc
        await self._db.refresh(subject)
        return subject

    async def update(
        self,
        *,
        user_id: uuid.UUID,
        subject_id: uuid.UUID,
        name: str | None = None,
        color_hex: str | None = None,
        sort_order: int | None = None,
        is_archived: bool | None = None,
    ) -> Subject:
        subject = await self.get_owned(user_id, subject_id)
        if name is not None:
            subject.name = name.strip()
        if color_hex is not None:
            subject.color_hex = color_hex
        if sort_order is not None:
            subject.sort_order = sort_order
        if is_archived is not None:
            subject.is_archived = is_archived

        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError(
                ErrorCode.SUBJECT_NAME_TAKEN,
                "You already have an active subject with that name.",
            ) from exc
        await self._db.refresh(subject)
        return subject

    async def reorder(
        self, *, user_id: uuid.UUID, ordered_ids: Sequence[uuid.UUID]
    ) -> list[Subject]:
        """Apply an explicit ordering; ids not listed keep their relative position after."""
        subjects = await self.list_for_user(user_id, include_archived=True)
        by_id = {subject.id: subject for subject in subjects}

        for position, subject_id in enumerate(ordered_ids):
            subject = by_id.get(subject_id)
            if subject is None:
                raise NotFoundError(
                    ErrorCode.SUBJECT_NOT_FOUND, "Subject not found.", subject_id=str(subject_id)
                )
            subject.sort_order = position

        offset = len(ordered_ids)
        remaining = [s for s in subjects if s.id not in set(ordered_ids)]
        for index, subject in enumerate(sorted(remaining, key=lambda s: s.sort_order)):
            subject.sort_order = offset + index

        await self._db.commit()
        return await self.list_for_user(user_id, include_archived=True)
