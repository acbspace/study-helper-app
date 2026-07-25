"""Liveness and readiness probes.

Liveness answers "is the process up"; readiness answers "can it serve traffic", which
means its dependencies must actually respond. Conflating them causes healthy pods to be
killed during a database blip.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.api.deps import DbDep
from app.core.logging import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe")
async def ready(db: DbDep, response: Response) -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("readiness_check_failed", component="database", error=str(exc))
        checks["database"] = "unavailable"

    ready_now = all(value == "ok" for value in checks.values())
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ready_now else "degraded", "checks": checks}
