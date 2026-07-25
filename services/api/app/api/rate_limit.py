"""Redis-backed rate limiting.

A fixed-window counter keyed by (route class, client ip). Disabled by default outside
production so local development and tests are not throttled. If Redis is unreachable the
limiter fails *open*: losing the cache must not lock users out of signing in.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)


def _client_key(request: Request) -> str:
    # X-Forwarded-For is only trusted behind a load balancer that sets it.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(
    request: Request, settings: Settings, *, bucket: str, limit: int, window_seconds: int = 60
) -> None:
    """Raise 429 when a caller exceeds `limit` requests in the window."""
    if not settings.rate_limit_enabled:
        return

    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return

    key = f"ratelimit:{bucket}:{_client_key(request)}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
    except Exception as exc:
        logger.warning("rate_limit_unavailable", bucket=bucket, error=str(exc))
        return

    if count > limit:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "Too many requests. Please try again shortly.",
            status_code=429,
            details={"retry_after_seconds": window_seconds},
        )


async def login_rate_limit(request: Request) -> None:
    settings: Settings = request.app.state.settings
    await enforce_rate_limit(
        request,
        settings,
        bucket="login",
        limit=settings.login_attempts_per_minute,
    )


async def social_rate_limit(request: Request) -> None:
    """Throttle outbound social actions — requests, invites, reactions, reports."""
    settings: Settings = request.app.state.settings
    await enforce_rate_limit(
        request,
        settings,
        bucket="social",
        limit=settings.social_writes_per_minute,
    )
