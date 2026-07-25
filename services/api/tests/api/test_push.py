"""Push delivery: batching, opt-in, idempotency, and retry-on-failure.

The provider is faked, so these tests pin the delivery *logic* — who gets a message, how the
message is shaped, and when a notification is (or is not) marked delivered — without touching
the network.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.domain.platform.push import PushMessage, PushService
from app.models.enums import NotificationKind
from app.models.platform import Notification
from app.models.user import Device, User


class FakeSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.batches: list[list[PushMessage]] = []

    async def send(self, messages: list[PushMessage]) -> None:
        if self.fail:
            raise RuntimeError("push provider unreachable")
        self.batches.append(messages)

    @property
    def sent(self) -> list[PushMessage]:
        return [message for batch in self.batches for message in batch]


async def _add_notification(
    db: AsyncSession, user: User, *, title: str = "New friend request"
) -> Notification:
    notification = Notification(
        user_id=user.id,
        kind=NotificationKind.FRIEND_REQUEST.value,
        title=title,
        body="Someone wants to study with you.",
        data={"friendship_id": "abc"},
    )
    db.add(notification)
    await db.flush()
    return notification


async def _add_device(db: AsyncSession, user: User, *, token: str | None) -> Device:
    device = Device(
        user_id=user.id,
        device_hash=uuid.uuid4().hex,
        platform="ios",
        push_token=token,
    )
    db.add(device)
    await db.flush()
    return device


class TestPushDelivery:
    async def test_delivers_to_each_registered_device(self, db: AsyncSession, user: User) -> None:
        await _add_device(db, user, token="ExponentPushToken[aaa]")
        await _add_device(db, user, token="ExponentPushToken[bbb]")
        notification = await _add_notification(db, user)
        await db.commit()

        sender = FakeSender()
        result = await PushService(db, sender).deliver_pending()

        assert result.considered == 1
        assert result.delivered == 2
        assert {message["to"] for message in sender.sent} == {
            "ExponentPushToken[aaa]",
            "ExponentPushToken[bbb]",
        }
        message = sender.sent[0]
        assert message["title"] == "New friend request"
        assert message["data"]["notification_id"] == str(notification.id)
        assert message["data"]["kind"] == "friend_request"
        assert message["data"]["friendship_id"] == "abc"

        await db.refresh(notification)
        assert notification.pushed_at is not None

    async def test_already_pushed_is_not_resent(self, db: AsyncSession, user: User) -> None:
        await _add_device(db, user, token="ExponentPushToken[aaa]")
        await _add_notification(db, user)
        await db.commit()

        sender = FakeSender()
        service = PushService(db, sender)
        await service.deliver_pending()
        second = await service.deliver_pending()

        assert second.considered == 0
        assert len(sender.sent) == 1  # only the first run sent anything

    async def test_opted_out_user_is_marked_but_not_sent(
        self, db: AsyncSession, user: User
    ) -> None:
        user.settings.notifications_enabled = False
        await _add_device(db, user, token="ExponentPushToken[aaa]")
        notification = await _add_notification(db, user)
        await db.commit()

        sender = FakeSender()
        result = await PushService(db, sender).deliver_pending()

        assert result.delivered == 0
        assert sender.sent == []
        # Still marked, so it is not reconsidered every run.
        await db.refresh(notification)
        assert notification.pushed_at is not None

    async def test_no_device_token_is_marked_but_not_sent(
        self, db: AsyncSession, user: User
    ) -> None:
        await _add_device(db, user, token=None)  # a device that never registered for push
        notification = await _add_notification(db, user)
        await db.commit()

        result = await PushService(db, FakeSender()).deliver_pending()
        assert result.delivered == 0
        await db.refresh(notification)
        assert notification.pushed_at is not None

    async def test_transport_failure_leaves_it_unpushed_for_retry(
        self, db: AsyncSession, user: User
    ) -> None:
        await _add_device(db, user, token="ExponentPushToken[aaa]")
        notification = await _add_notification(db, user)
        await db.commit()

        with pytest.raises(RuntimeError):
            await PushService(db, FakeSender(fail=True)).deliver_pending()
        await db.rollback()

        await db.refresh(notification)
        assert notification.pushed_at is None  # will be retried next run

    async def test_stale_backlog_is_ignored(self, db: AsyncSession, user: User) -> None:
        await _add_device(db, user, token="ExponentPushToken[aaa]")
        old = await _add_notification(db, user, title="Ancient")
        await db.flush()
        # Backdate it beyond the delivery horizon.
        old.created_at = utc_now().replace(year=2020)
        await db.commit()

        result = await PushService(db, FakeSender()).deliver_pending()
        assert result.considered == 0

    async def test_nothing_pending_is_a_noop(self, db: AsyncSession, user: User) -> None:
        result = await PushService(db, FakeSender()).deliver_pending()
        assert result == result.__class__(considered=0, delivered=0)
