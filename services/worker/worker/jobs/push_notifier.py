"""Deliver pending notifications as push messages.

Thin wrapper over `PushService`: all of the batching, opt-in, and idempotency logic lives in
the domain service (and is unit-tested there); this just opens a session and runs it on a
schedule. Runs frequently because a notification is only useful while it is fresh.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.domain.platform.push import PushService, build_push_sender
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def run(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ entry point."""
    factory = ctx["session_factory"]
    session: AsyncSession
    async with factory() as session:
        service = PushService(session, build_push_sender())
        result = await service.deliver_pending()
    return {"considered": result.considered, "delivered": result.delivered}
