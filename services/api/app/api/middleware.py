"""Request correlation, access logging, response hardening, and a request body ceiling.

All three are pure ASGI middleware rather than Starlette's `BaseHTTPMiddleware`. That base
class wraps every request in an extra task and buffers through an anyio stream, which costs
throughput on a hot path and interferes with streaming responses; at this layer — where every
single request pays the cost — the plain ASGI form is worth the slightly lower-level code.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware:
    """Attach a request id to logs and echo it back for support correlation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "request_failed",
                method=scope.get("method"),
                path=_route_template(scope),
                duration_ms=_elapsed_ms(started),
            )
            raise
        else:
            logger.info(
                "request_completed",
                method=scope.get("method"),
                # The route template, not the raw path: raw paths embed record ids, which
                # makes every request a unique log line and every metric label unbounded.
                path=_route_template(scope),
                status_code=status_code,
                duration_ms=_elapsed_ms(started),
            )
        finally:
            request_id_ctx.reset(token)


class SecurityHeadersMiddleware:
    """Set the response headers a browser needs to defend the user.

    The API is consumed by native clients and a SPA, never rendered as HTML, so the policy is
    the restrictive one: deny framing, no sniffing, no referrer leakage, and a CSP that
    forbids loading anything at all. The interactive docs are the one HTML surface, so they
    are exempted from the CSP rather than being quietly broken by it.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_docs = path in ("/docs", "/redoc") or path.endswith("/openapi.json")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", "default-src 'none'")
                # Only meaningful over TLS, and actively harmful on a local HTTP origin
                # because a browser would refuse plain http:// to localhost afterwards.
                if self.settings.is_deployed:
                    headers.setdefault(
                        "Strict-Transport-Security",
                        f"max-age={self.settings.hsts_max_age_seconds}; includeSubDomains",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class MaxBodySizeMiddleware:
    """Reject request bodies above a ceiling, before they are buffered.

    A declared `Content-Length` is refused outright; a chunked body is measured as it
    arrives and cut off once it exceeds the limit, so neither form can be used to make the
    process allocate without bound.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _too_large(send, self.max_bytes)
            return

        received = 0
        exceeded = False

        async def receive_wrapper() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    # Stop the stream rather than keep buffering a body we will not read.
                    return {"type": "http.disconnect"}
            return message

        async def send_wrapper(message: Message) -> None:
            if exceeded and message["type"] == "http.response.start":
                await _too_large(send, self.max_bytes)
                return
            if exceeded and message["type"] == "http.response.body":
                return
            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)


async def _too_large(send: Send, max_bytes: int) -> None:
    import json

    body = json.dumps(
        {
            "error": {
                "code": "validation_error",
                "message": "Request body is too large.",
                "details": {"max_bytes": max_bytes},
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _route_template(scope: Scope) -> str:
    """The matched route pattern where routing has happened, else the raw path."""
    route: Any = scope.get("route")
    path_format = getattr(route, "path_format", None)
    if isinstance(path_format, str):
        return path_format
    path: str = scope.get("path", "")
    return path


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
