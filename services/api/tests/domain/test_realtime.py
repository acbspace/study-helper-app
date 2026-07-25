"""Realtime primitives: the hub, the local broadcaster, and WebSocket tickets."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import create_access_token, mint_ws_ticket, verify_ws_ticket
from app.domain.realtime.broadcaster import Broadcaster
from app.domain.realtime.hub import RealtimeConnection, RealtimeHub


class TestHub:
    async def test_publish_delivers_to_each_subscriber(self) -> None:
        hub = RealtimeHub()
        a = RealtimeConnection(uuid.uuid4())
        b = RealtimeConnection(uuid.uuid4())
        hub.subscribe(a, ["friends:x"])
        hub.subscribe(b, ["friends:x"])

        assert hub.publish("friends:x", {"event": "e"}) == 2
        assert a.queue.get_nowait() == {"event": "e"}
        assert b.queue.get_nowait() == {"event": "e"}

    async def test_publish_to_empty_channel_is_a_noop(self) -> None:
        hub = RealtimeHub()
        assert hub.publish("nobody", {"event": "e"}) == 0

    async def test_unsubscribe_stops_delivery(self) -> None:
        hub = RealtimeHub()
        conn = RealtimeConnection(uuid.uuid4())
        hub.subscribe(conn, ["c"])
        hub.unsubscribe(conn, ["c"])
        assert hub.publish("c", {"event": "e"}) == 0

    async def test_disconnect_removes_from_all_channels(self) -> None:
        hub = RealtimeHub()
        conn = RealtimeConnection(uuid.uuid4())
        hub.subscribe(conn, ["a", "b"])
        hub.disconnect(conn)
        assert hub.local_subscriber_count("a") == 0
        assert hub.local_subscriber_count("b") == 0
        assert conn.channels == set()

    async def test_closed_connection_ignores_delivery(self) -> None:
        conn = RealtimeConnection(uuid.uuid4())
        conn.close()  # enqueues the stop sentinel
        conn.deliver({"event": "late"})
        # Only the sentinel is queued; the post-close delivery was dropped.
        assert conn.queue.get_nowait() is None
        assert conn.queue.empty()


class TestBroadcasterLocal:
    async def test_publish_delivers_locally_without_redis(self) -> None:
        hub = RealtimeHub()
        conn = RealtimeConnection(uuid.uuid4())
        hub.subscribe(conn, ["room"])
        broadcaster = Broadcaster(hub, redis=None)

        assert broadcaster.uses_redis is False
        await broadcaster.publish("room", {"event": "hello"})
        assert conn.queue.get_nowait() == {"event": "hello"}


class TestWsTickets:
    def test_ticket_roundtrips(self, settings: Settings) -> None:
        user_id = uuid.uuid4()
        ticket, expires_in = mint_ws_ticket(settings, user_id)
        assert expires_in == settings.ws_ticket_ttl_seconds
        assert verify_ws_ticket(settings, ticket) == user_id

    def test_access_token_is_not_accepted_as_a_ticket(self, settings: Settings) -> None:
        """A leaked API bearer must not double as a socket ticket."""
        access, _ = create_access_token(settings, uuid.uuid4())
        with pytest.raises(AppError):
            verify_ws_ticket(settings, access)

    def test_expired_ticket_is_rejected(self, settings: Settings) -> None:
        past = datetime.now(UTC) - timedelta(seconds=settings.ws_ticket_ttl_seconds + 30)
        ticket, _ = mint_ws_ticket(settings, uuid.uuid4(), now=past)
        with pytest.raises(AppError):
            verify_ws_ticket(settings, ticket)

    def test_garbage_ticket_is_rejected(self, settings: Settings) -> None:
        with pytest.raises(AppError):
            verify_ws_ticket(settings, "not-a-jwt")
