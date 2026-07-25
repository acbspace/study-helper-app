"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import RequestContextMiddleware
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_session_factory
from app.domain.realtime.broadcaster import Broadcaster
from app.domain.realtime.hub import RealtimeHub
from app.domain.social.presence import build_presence_store

logger = get_logger(__name__)

API_V1_PREFIX = "/api/v1"


def _build_lifespan(settings: Settings) -> Any:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = await _connect_redis(settings)
        app.state.presence_store = build_presence_store(app.state.redis)

        # Realtime fan-out: one hub per process, plus a Redis subscriber that forwards
        # cross-instance messages into it. Without Redis the broadcaster delivers locally.
        hub = RealtimeHub()
        broadcaster = Broadcaster(hub, app.state.redis)
        app.state.realtime_hub = hub
        app.state.broadcaster = broadcaster
        subscriber = asyncio.create_task(broadcaster.run()) if broadcaster.uses_redis else None

        logger.info("api_started", environment=settings.environment.value)
        try:
            yield
        finally:
            if subscriber is not None:
                subscriber.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await subscriber
            if app.state.redis is not None:
                await app.state.redis.aclose()
            await engine.dispose()
            logger.info("api_stopped")

    return lifespan


async def _connect_redis(settings: Settings) -> Any:
    """Connect to Redis, tolerating its absence.

    Redis powers presence and rate limiting, neither of which is required for the timer to
    work; a local developer without Redis should still get a usable API.
    """
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:
        logger.warning("redis_unavailable", error=str(exc))
        return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Study League API",
        version="0.1.0",
        description="Study timer, planner, statistics, and seasonal league backend.",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url=f"{API_V1_PREFIX}/openapi.json" if settings.docs_enabled else None,
        lifespan=_build_lifespan(settings),
    )

    # Request dependencies read configuration from here rather than the global cache, so
    # the app always behaves according to the settings it was constructed with.
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    _register_exception_handlers(app)
    app.include_router(api_router, prefix=API_V1_PREFIX)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        headers = {}
        if exc.code is ErrorCode.RATE_LIMITED:
            headers["Retry-After"] = str(exc.details.get("retry_after_seconds", 60))
        return JSONResponse(
            status_code=exc.status_code, content=exc.to_payload(), headers=headers or None
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": "The request body failed validation.",
                    "details": {"fields": _summarise_validation(exc)},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: ErrorCode.NOT_AUTHENTICATED,
            403: ErrorCode.NOT_PERMITTED,
        }.get(exc.status_code, ErrorCode.VALIDATION_ERROR)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code.value, "message": str(exc.detail)}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: internals must not leak to clients.
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": "Something went wrong. Please try again.",
                }
            },
        )


def _summarise_validation(exc: RequestValidationError) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        fields.append({"field": location or "body", "message": str(error.get("msg", ""))})
    return fields


app = create_app()
