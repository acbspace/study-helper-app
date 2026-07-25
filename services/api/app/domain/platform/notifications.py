"""In-app notifications and push-token registration.

Notifications are durable rows, deliberately not socket events: a friend request that arrives
while the app is closed must still be there on next launch. The realtime socket accelerates
*live* state; this is the record.

Push delivery itself (Expo) is a worker concern — this module owns the token registration and
the in-app inbox, so the delivery job has something to read.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.errors import AppError, ErrorCode, NotFoundError
from app.models.enums import NotificationKind
from app.models.platform import Notification
from app.models.user import Device


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        kind: NotificationKind,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            kind=kind.value,
            title=title,
            body=body,
            data=data or {},
        )
        self._db.add(notification)
        await self._db.commit()
        await self._db.refresh(notification)
        return notification

    async def list_for(
        self, user_id: uuid.UUID, *, limit: int = 50, unread_only: bool = False
    ) -> list[Notification]:
        query = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        result = await self._db.execute(query.order_by(Notification.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def unread_count(self, user_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        return int(result.scalar_one())

    async def mark_read(self, *, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
        result = await self._db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            raise NotFoundError(ErrorCode.NOTIFICATION_NOT_FOUND, "Notification not found.")
        if notification.read_at is None:
            notification.read_at = utc_now()
            await self._db.commit()
            await self._db.refresh(notification)
        return notification

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(Notification).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        now = utc_now()
        rows = list(result.scalars().all())
        for row in rows:
            row.read_at = now
        if rows:
            await self._db.commit()
        return len(rows)

    async def register_push_token(
        self, *, user_id: uuid.UUID, device_id: uuid.UUID | None, token: str, platform: str
    ) -> None:
        """Attach an Expo push token to the calling device.

        Requires the device header: a token without a device would leak notifications to
        whatever installation happened to register last.
        """
        if device_id is None:
            raise AppError(
                ErrorCode.DEVICE_REQUIRED,
                "An X-Device-Id header is required to register for push.",
            )
        result = await self._db.execute(
            select(Device).where(Device.id == device_id, Device.user_id == user_id)
        )
        device = result.scalar_one_or_none()
        if device is None:
            raise NotFoundError(ErrorCode.NOT_AUTHENTICATED, "Device not found.")
        device.push_token = token
        device.platform = platform
        device.last_seen_at = utc_now()
        await self._db.commit()
