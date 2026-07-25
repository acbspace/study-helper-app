"""Realtime routes: a WebSocket ticket, encouragement reactions, and the socket itself.

The socket is authenticated by a short-lived ticket in the query string (never the access
token), then the client subscribes to channels it is authorized for. Each connection runs a
reader (incoming ops) and a writer (draining a per-connection queue), so one slow socket can
never block fan-out.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from app.api.deps import (
    CurrentUser,
    RealtimeServiceDep,
    SettingsDep,
    get_broadcaster,
    get_realtime_hub,
)
from app.api.rate_limit import social_rate_limit
from app.core.clock import utc_now
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import mint_ws_ticket, verify_ws_ticket
from app.domain.realtime.broadcaster import Broadcaster
from app.domain.realtime.hub import RealtimeConnection, RealtimeHub
from app.domain.realtime.service import RealtimeService, resolve_channel_tokens
from app.schemas.realtime import ReactionRequest, TicketResponse

logger = get_logger(__name__)

router = APIRouter(tags=["realtime"])

_WS_UNAUTHORIZED = 4401
_MAX_CHANNELS = 100


@router.post("/realtime/ticket", response_model=TicketResponse, summary="Mint a realtime ticket")
async def create_ticket(user: CurrentUser, settings: SettingsDep) -> TicketResponse:
    ticket, expires_in = mint_ws_ticket(settings, user.id, now=utc_now())
    return TicketResponse(ticket=ticket, expires_in=expires_in)


@router.post(
    "/realtime/reactions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Send an encouragement reaction",
    dependencies=[Depends(social_rate_limit)],
)
async def send_reaction(
    payload: ReactionRequest, user: CurrentUser, realtime: RealtimeServiceDep
) -> None:
    await realtime.publish_reaction(sender=user, target_id=payload.target_id, emoji=payload.emoji)


@router.websocket("/realtime")
async def realtime_ws(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    try:
        user_id = verify_ws_ticket(settings, websocket.query_params.get("token", ""))
    except AppError:
        await websocket.close(code=_WS_UNAUTHORIZED)
        return

    hub = get_realtime_hub(websocket.app.state)
    broadcaster = get_broadcaster(websocket.app.state)
    conn = RealtimeConnection(user_id)
    await websocket.accept()

    writer = asyncio.create_task(_writer(websocket, conn))
    try:
        while True:
            raw = await websocket.receive_json()
            await _handle_op(websocket, conn, hub, broadcaster, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # a malformed frame should close the socket, not crash the worker
        logger.warning("realtime_socket_error", error=str(exc))
    finally:
        conn.close()
        hub.disconnect(conn)
        writer.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await writer


async def _writer(websocket: WebSocket, conn: RealtimeConnection) -> None:
    """Drain the connection's queue to the socket until a sentinel (None) arrives."""
    while True:
        message = await conn.queue.get()
        if message is None:
            return
        await websocket.send_json(message)


async def _handle_op(
    websocket: WebSocket,
    conn: RealtimeConnection,
    hub: RealtimeHub,
    broadcaster: Broadcaster,
    raw: object,
) -> None:
    if not isinstance(raw, dict):
        return
    op = raw.get("op")
    tokens = _channel_tokens(raw.get("channels"))

    if op == "subscribe":
        async with websocket.app.state.session_factory() as db:
            service = RealtimeService(db, broadcaster)
            allowed = await service.authorize_channels(conn.user_id, tokens)
        hub.subscribe(conn, allowed)
        conn.deliver({"event": "subscribed", "data": {"channels": allowed}})
    elif op == "unsubscribe":
        concrete = resolve_channel_tokens(conn.user_id, tokens)
        hub.unsubscribe(conn, concrete)
        conn.deliver({"event": "unsubscribed", "data": {"channels": concrete}})
    elif op == "ping":
        conn.deliver({"event": "pong"})


def _channel_tokens(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)][:_MAX_CHANNELS]
