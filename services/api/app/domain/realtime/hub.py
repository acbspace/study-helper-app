"""In-process registry of connected sockets, indexed by channel.

The hub knows nothing about WebSockets, Redis, or the database — it just maps channel names
to local connections and pushes messages onto per-connection queues. That keeps fan-out
delivery non-blocking (a slow socket cannot stall a publisher) and makes the whole thing
unit-testable without any I/O.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Iterable
from typing import Any

# Messages are already-built JSON-safe dicts.
Message = dict[str, Any]

# A slow consumer that fills its buffer is dropping-tolerant by design: presence is lossy and
# clients reconcile over REST, so we bound the queue rather than grow memory unboundedly.
_MAX_QUEUE = 128


class RealtimeConnection:
    """One connected socket. Delivery is buffered through a queue drained by a writer task."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.channels: set[str] = set()
        self.queue: asyncio.Queue[Message | None] = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._open = True

    def deliver(self, message: Message) -> None:
        """Enqueue a message for the writer. Drops rather than blocks if the socket is slow."""
        if not self._open:
            return
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(message)

    def close(self) -> None:
        """Stop accepting messages and unblock the writer with a sentinel."""
        self._open = False
        with contextlib.suppress(asyncio.QueueFull):
            self.queue.put_nowait(None)


class RealtimeHub:
    def __init__(self) -> None:
        self._by_channel: dict[str, set[RealtimeConnection]] = {}

    def subscribe(self, conn: RealtimeConnection, channels: Iterable[str]) -> None:
        for channel in channels:
            self._by_channel.setdefault(channel, set()).add(conn)
            conn.channels.add(channel)

    def unsubscribe(self, conn: RealtimeConnection, channels: Iterable[str]) -> None:
        for channel in channels:
            self._by_channel.get(channel, set()).discard(conn)
            conn.channels.discard(channel)

    def disconnect(self, conn: RealtimeConnection) -> None:
        for channel in list(conn.channels):
            subscribers = self._by_channel.get(channel)
            if subscribers is not None:
                subscribers.discard(conn)
                if not subscribers:
                    del self._by_channel[channel]
        conn.channels.clear()

    def publish(self, channel: str, message: Message) -> int:
        """Deliver to every local subscriber of `channel`. Returns how many received it."""
        subscribers = self._by_channel.get(channel)
        if not subscribers:
            return 0
        for conn in list(subscribers):
            conn.deliver(message)
        return len(subscribers)

    def local_subscriber_count(self, channel: str) -> int:
        return len(self._by_channel.get(channel, ()))
