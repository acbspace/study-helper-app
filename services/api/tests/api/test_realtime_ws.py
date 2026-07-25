"""End-to-end realtime: the ticket REST endpoint, reactions, and the WebSocket itself.

The socket is driven through a tiny in-loop ASGI harness so it runs in the same event loop
as the async test database — no separate TestClient loop, so `session_factory` (an async
engine bound to this loop) works inside the socket handler. Redis is absent, so the
broadcaster delivers locally, which is exactly the single-instance path.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.main import create_app

WS_PATH = "/api/v1/realtime"


@pytest_asyncio.fixture
async def realtime_app(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> Any:
    app = create_app(settings)
    app.state.session_factory = session_factory
    app.state.redis = None
    return app


@pytest_asyncio.fixture
async def http(realtime_app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=realtime_app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        yield client


class WSDriver:
    """Drives the ASGI websocket protocol by hand, in-loop."""

    def __init__(self, app: Any, token: str) -> None:
        self._app = app
        self._scope = {
            "type": "websocket",
            "path": WS_PATH,
            "raw_path": WS_PATH.encode(),
            "query_string": f"token={token}".encode(),
            "headers": [],
            "subprotocols": [],
            "client": ("testclient", 123),
            "scheme": "ws",
        }
        self._inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(
            self._app(self._scope, self._inbound.get, self._outbound.put)
        )
        await self._inbound.put({"type": "websocket.connect"})

    async def next(self, timeout: float = 1.0) -> dict[str, Any]:
        return await asyncio.wait_for(self._outbound.get(), timeout)

    async def accept(self) -> None:
        frame = await self.next()
        assert frame["type"] == "websocket.accept", frame

    async def send_json(self, data: dict[str, Any]) -> None:
        await self._inbound.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def receive_json(self, timeout: float = 1.0) -> dict[str, Any]:
        frame = await self.next(timeout)
        assert frame["type"] == "websocket.send", frame
        return json.loads(frame["text"])

    async def close(self) -> None:
        await self._inbound.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=1.0)


async def _register(http: AsyncClient, *, email: str, username: str) -> tuple[str, dict[str, str]]:
    response = await http.post(
        "/auth/register",
        json={
            "email": email,
            "password": "test-passphrase-9x",
            "username": username,
            "display_name": username.title(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["user"]["id"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


async def _befriend(http: AsyncClient, a: dict[str, str], b_id: str, b: dict[str, str]) -> None:
    sent = await http.post("/friends/requests", json={"user_id": b_id}, headers=a)
    await http.post(f"/friends/requests/{sent.json()['friendship_id']}/accept", headers=b)


async def _ticket(http: AsyncClient, headers: dict[str, str]) -> str:
    response = await http.post("/realtime/ticket", headers=headers)
    assert response.status_code == 200, response.text
    return str(response.json()["ticket"])


class TestTicketEndpoint:
    async def test_ticket_requires_auth(self, http: AsyncClient) -> None:
        assert (await http.post("/realtime/ticket")).status_code == 401

    async def test_ticket_is_minted(self, http: AsyncClient) -> None:
        _, headers = await _register(http, email="a@example.com", username="alice")
        response = await http.post("/realtime/ticket", headers=headers)
        assert response.status_code == 200
        assert response.json()["ticket"]
        assert response.json()["expires_in"] > 0


class TestWebSocket:
    async def test_bad_ticket_is_rejected(self, realtime_app: Any) -> None:
        driver = WSDriver(realtime_app, token="not-a-real-ticket")
        await driver.start()
        frame = await driver.next()
        assert frame["type"] == "websocket.close"
        assert frame["code"] == 4401

    async def test_ping_pong(self, realtime_app: Any, http: AsyncClient) -> None:
        _, headers = await _register(http, email="a@example.com", username="alice")
        driver = WSDriver(realtime_app, token=await _ticket(http, headers))
        await driver.start()
        await driver.accept()

        await driver.send_json({"op": "ping"})
        assert (await driver.receive_json())["event"] == "pong"
        await driver.close()

    async def test_subscribe_then_receive_friend_presence(
        self, realtime_app: Any, http: AsyncClient
    ) -> None:
        a_id, a = await _register(http, email="a@example.com", username="alice")
        b_id, b = await _register(http, email="b@example.com", username="bob")
        await _befriend(http, a, b_id, b)

        driver = WSDriver(realtime_app, token=await _ticket(http, a))
        await driver.start()
        await driver.accept()
        await driver.send_json({"op": "subscribe", "channels": ["friends"]})
        ack = await driver.receive_json()
        assert ack["event"] == "subscribed"
        assert ack["data"]["channels"] == [f"friends:{a_id}"]

        # Bob starts studying → Alice's socket should hear about it.
        assert (
            await http.put("/presence/heartbeat", json={"state": "studying"}, headers=b)
        ).status_code == 204

        event = await driver.receive_json()
        assert event["event"] == "presence.changed"
        assert event["data"]["user"]["id"] == b_id
        assert event["data"]["state"] == "studying"
        await driver.close()

    async def test_private_group_channel_is_refused(
        self, realtime_app: Any, http: AsyncClient
    ) -> None:
        _, owner = await _register(http, email="o@example.com", username="owner")
        _, outsider = await _register(http, email="x@example.com", username="outsider")
        created = await http.post(
            "/groups", json={"name": "Secret", "visibility": "private"}, headers=owner
        )
        gid = created.json()["group"]["id"]

        driver = WSDriver(realtime_app, token=await _ticket(http, outsider))
        await driver.start()
        await driver.accept()
        await driver.send_json({"op": "subscribe", "channels": [f"group:{gid}"]})
        ack = await driver.receive_json()
        # The unauthorized channel is silently dropped from the allowed set.
        assert ack["data"]["channels"] == []
        await driver.close()

    async def test_reaction_is_delivered(self, realtime_app: Any, http: AsyncClient) -> None:
        a_id, a = await _register(http, email="a@example.com", username="alice")
        b_id, b = await _register(http, email="b@example.com", username="bob")
        await _befriend(http, a, b_id, b)

        driver = WSDriver(realtime_app, token=await _ticket(http, a))
        await driver.start()
        await driver.accept()
        await driver.send_json({"op": "subscribe", "channels": ["friends"]})
        await driver.receive_json()  # subscribed ack

        reacted = await http.post(
            "/realtime/reactions", json={"target_id": a_id, "emoji": "clap"}, headers=b
        )
        assert reacted.status_code == 204

        event = await driver.receive_json()
        assert event["event"] == "reaction.created"
        assert event["data"]["from"]["id"] == b_id
        assert event["data"]["emoji"] == "clap"
        await driver.close()

    async def test_reaction_to_non_friend_is_not_found(self, http: AsyncClient) -> None:
        a_id, _ = await _register(http, email="a@example.com", username="alice")
        _, b = await _register(http, email="b@example.com", username="bob")
        response = await http.post(
            "/realtime/reactions", json={"target_id": a_id, "emoji": "fire"}, headers=b
        )
        assert response.status_code == 404
