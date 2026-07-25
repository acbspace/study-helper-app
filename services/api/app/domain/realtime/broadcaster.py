"""Fan-out across API instances.

`publish` is the only producer entry point. With Redis, every publish goes to a Redis
pub/sub channel and comes back to *all* instances (including this one) through a single
subscriber loop, which forwards to the local hub — so a message is delivered exactly once per
socket regardless of which instance produced it, and scaling out is just running more
instances. Without Redis (single instance, dev, tests) `publish` delivers to the local hub
directly. Either way the API code above is identical.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from app.core.logging import get_logger
from app.domain.realtime.hub import Message, RealtimeHub

logger = get_logger(__name__)

# Redis channel namespace, kept distinct from presence/ratelimit keys.
_PREFIX = "rt:"


class Broadcaster:
    def __init__(self, hub: RealtimeHub, redis: Any = None) -> None:
        self._hub = hub
        self._redis = redis

    @property
    def uses_redis(self) -> bool:
        return self._redis is not None

    async def publish(self, channel: str, message: Message) -> None:
        if self._redis is None:
            self._hub.publish(channel, message)
            return
        try:
            await self._redis.publish(_PREFIX + channel, json.dumps(message))
        except Exception as exc:  # fan-out must never break the producing request
            logger.warning("realtime_publish_failed", channel=channel, error=str(exc))
            # Best-effort local delivery so a single-node cluster still works if Redis blips.
            self._hub.publish(channel, message)

    async def run(self) -> None:
        """Forward every realtime message from Redis to local sockets. Runs for the app's life."""
        if self._redis is None:
            return
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(_PREFIX + "*")
        logger.info("realtime_subscriber_started")
        try:
            async for raw in pubsub.listen():
                if raw.get("type") != "pmessage":
                    continue
                self._dispatch(str(raw.get("channel", "")), raw.get("data"))
        finally:
            with contextlib.suppress(Exception):  # shutdown best-effort
                await pubsub.aclose()

    def _dispatch(self, redis_channel: str, data: object) -> None:
        channel = redis_channel.removeprefix(_PREFIX)
        if not isinstance(data, str):
            return
        try:
            message: Message = json.loads(data)
        except (ValueError, TypeError):
            return
        self._hub.publish(channel, message)
