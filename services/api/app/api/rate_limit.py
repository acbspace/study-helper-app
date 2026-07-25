"""Redis-backed rate limiting.

A sliding-window counter keyed by (route class, caller). "Caller" is the authenticated user
where one exists and the client IP otherwise, because an attacker rotates IPs far more easily
than accounts, and a shared NAT should not throttle a whole school on one user's behaviour.

If Redis is unreachable the limiter fails *open*: losing the cache must not lock users out of
signing in. That is a deliberate availability-over-enforcement trade, and it is why
`RATE_LIMIT_ENABLED` being on is enforced at boot rather than left to a deployment to notice.
"""

from __future__ import annotations

import time
import uuid

from fastapi import Request

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decode_access_token

logger = get_logger(__name__)

MINUTE = 60
HOUR = 3600


def client_ip(request: Request) -> str:
    """The caller's IP, honouring only as many proxy hops as are actually trusted.

    `X-Forwarded-For` is appended to by each proxy, so the rightmost entries are the ones
    written by infrastructure we control and the leftmost are whatever the client sent. Taking
    the *left* entry — the obvious reading — lets any caller mint a fresh rate-limit bucket per
    request simply by setting the header, which defeats the limiter entirely. So we count
    `trusted_proxy_hops` from the right, and ignore the header completely when there is no
    proxy in front of us.
    """
    settings: Settings = request.app.state.settings
    hops = settings.trusted_proxy_hops
    if hops <= 0:
        return request.client.host if request.client else "unknown"

    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return request.client.host if request.client else "unknown"

    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return request.client.host if request.client else "unknown"

    # hops=1 → the last entry was written by our own proxy and names the real client.
    index = len(chain) - hops
    if index < 0:
        # Fewer entries than expected: the chain is shorter than configured, so the
        # left-most value is the furthest back we can go and still be reading our own
        # infrastructure's word for it.
        index = 0
    return chain[index]


def _caller_key(request: Request) -> str:
    """Prefer the authenticated user; fall back to IP for anonymous routes.

    The token is decoded here rather than read from a resolved `CurrentUser`: route-level
    dependencies run before the endpoint's own parameters, so the user is not available yet.
    Verifying the signature is cheap and needs no database round trip, and an unreadable
    token simply falls through to IP keying — this is a bucket key, not an authorization
    decision, so being wrong costs a coarser limit and nothing more.
    """
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("Authorization")
    if authorization and authorization.lower().startswith("bearer "):
        try:
            user_id = decode_access_token(settings, authorization.split(" ", 1)[1].strip())
            return f"user:{user_id}"
        except AppError:
            pass
    return f"ip:{client_ip(request)}"


async def enforce_rate_limit(
    request: Request, settings: Settings, *, bucket: str, limit: int, window_seconds: int = MINUTE
) -> None:
    """Raise 429 when a caller exceeds `limit` requests within the trailing window.

    A sliding window rather than a fixed one: with fixed windows a caller gets `2 * limit`
    requests across a boundary, which for login attempts is exactly the burst that matters.
    """
    if not settings.rate_limit_enabled:
        return

    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return

    key = f"ratelimit:{bucket}:{_caller_key(request)}"
    now = time.time()
    cutoff = now - window_seconds

    try:
        # One round trip: drop what aged out, add this hit, count what remains, and let the
        # key expire on its own so idle callers cost nothing.
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        count = int(results[2])
    except Exception as exc:
        logger.warning("rate_limit_unavailable", bucket=bucket, error=str(exc))
        return

    if count > limit:
        logger.info("rate_limited", bucket=bucket, limit=limit, window_seconds=window_seconds)
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "Too many requests. Please try again shortly.",
            status_code=429,
            details={"retry_after_seconds": window_seconds},
        )


async def login_rate_limit(request: Request) -> None:
    settings: Settings = request.app.state.settings
    await enforce_rate_limit(
        request, settings, bucket="login", limit=settings.login_attempts_per_minute
    )


async def register_rate_limit(request: Request) -> None:
    """Throttle account creation — unmetered signup is how a service becomes a spam host."""
    settings: Settings = request.app.state.settings
    await enforce_rate_limit(
        request,
        settings,
        bucket="register",
        limit=settings.registrations_per_hour,
        window_seconds=HOUR,
    )


async def refresh_rate_limit(request: Request) -> None:
    """Bound refresh-token guessing. Legitimate refreshes stay far under this."""
    settings: Settings = request.app.state.settings
    await enforce_rate_limit(
        request, settings, bucket="refresh", limit=settings.refresh_attempts_per_minute
    )


async def password_reset_rate_limit(request: Request) -> None:
    """Reset requests are per-hour: the cost of abuse lands in someone else's inbox."""
    settings: Settings = request.app.state.settings
    await enforce_rate_limit(
        request,
        settings,
        bucket="password_reset",
        limit=settings.password_resets_per_hour,
        window_seconds=HOUR,
    )


async def social_rate_limit(request: Request) -> None:
    """Throttle outbound social actions — requests, invites, reactions, reports."""
    settings: Settings = request.app.state.settings
    await enforce_rate_limit(
        request, settings, bucket="social", limit=settings.social_writes_per_minute
    )
