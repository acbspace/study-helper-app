"""Push delivery for notifications.

The durable notification row is created synchronously by whatever triggered it (a friend
request, a group invite); *delivery* is this separate, retryable step, so a slow or failing
push provider can never slow down or break the request that produced the notification.

Idempotency is the `notifications.pushed_at` marker: the worker only picks up rows where it is
NULL and stamps it once they are considered, so a retried or overlapping run never double-sends.
A transport failure leaves the marker NULL (the surrounding transaction rolls back), so the
batch is simply retried next tick.

The provider is injected (`PushSender`), which keeps all of the batching, privacy, and
idempotency logic unit-testable without touching the network.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.logging import get_logger
from app.models.platform import Notification
from app.models.user import Device, UserSettings

logger = get_logger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_BATCH_SIZE = 100
# Never push a backlog that built up while the worker was down — a burst of day-old pings
# helps nobody. Older unpushed rows are simply left as read-in-app only.
DEFAULT_HORIZON_HOURS = 24

PushMessage = dict[str, Any]


class PushSender(Protocol):
    """Sends a batch of already-built push messages. Raises on transport failure."""

    async def send(self, messages: list[PushMessage]) -> None: ...


@dataclass(frozen=True, slots=True)
class PushResult:
    considered: int
    delivered: int


class PushService:
    def __init__(self, db: AsyncSession, sender: PushSender) -> None:
        self._db = db
        self._sender = sender

    async def deliver_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int = 200,
        horizon_hours: int = DEFAULT_HORIZON_HOURS,
    ) -> PushResult:
        moment = now or utc_now()
        horizon = moment - timedelta(hours=horizon_hours)

        result = await self._db.execute(
            select(Notification)
            .where(Notification.pushed_at.is_(None), Notification.created_at >= horizon)
            .order_by(Notification.created_at)
            .limit(limit)
        )
        pending = list(result.scalars().all())
        if not pending:
            return PushResult(considered=0, delivered=0)

        user_ids = {notification.user_id for notification in pending}
        opted_in = await self._opted_in_users(user_ids)
        tokens = await self._tokens_by_user(user_ids)

        messages: list[PushMessage] = []
        for notification in pending:
            if notification.user_id not in opted_in:
                continue
            for token in tokens.get(notification.user_id, []):
                messages.append(_build_message(notification, token))

        # Send first; only stamp the markers if it succeeded, so a failure is retried whole.
        if messages:
            await self._sender.send(messages)

        for notification in pending:
            notification.pushed_at = moment
        await self._db.commit()

        logger.info("push_deliver_finished", considered=len(pending), delivered=len(messages))
        return PushResult(considered=len(pending), delivered=len(messages))

    async def _opted_in_users(self, user_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        result = await self._db.execute(
            select(UserSettings.user_id).where(
                UserSettings.user_id.in_(user_ids),
                UserSettings.notifications_enabled.is_(True),
            )
        )
        return set(result.scalars().all())

    async def _tokens_by_user(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        result = await self._db.execute(
            select(Device.user_id, Device.push_token).where(
                Device.user_id.in_(user_ids), Device.push_token.is_not(None)
            )
        )
        tokens: dict[uuid.UUID, list[str]] = defaultdict(list)
        for user_id, token in result.all():
            if token:
                tokens[user_id].append(token)
        return tokens


def _build_message(notification: Notification, token: str) -> PushMessage:
    return {
        "to": token,
        "title": notification.title,
        "body": notification.body,
        "sound": "default",
        "data": {
            **notification.data,
            "notification_id": str(notification.id),
            "kind": notification.kind,
        },
    }


class ExpoPushSender:
    """Delivers via the Expo push service, in chunks of at most 100 messages."""

    def __init__(self, url: str = EXPO_PUSH_URL) -> None:
        self._url = url

    async def send(self, messages: list[PushMessage]) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            for start in range(0, len(messages), EXPO_BATCH_SIZE):
                chunk = messages[start : start + EXPO_BATCH_SIZE]
                response = await client.post(
                    self._url,
                    json=chunk,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                response.raise_for_status()


def build_push_sender() -> PushSender:
    return ExpoPushSender()
