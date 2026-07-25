"""ARQ worker entry point.

Run with:  python -m arq worker.main.WorkerSettings
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_session_factory
from arq import cron
from arq.connections import RedisSettings

from worker.jobs import league_scorer, push_notifier, session_reaper

logger = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    logger.info("worker_started", environment=settings.environment.value)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()
    logger.info("worker_stopped")


class WorkerSettings:
    """ARQ configuration.

    Jobs are idempotent, so a retry or an overlapping run cannot corrupt state — the
    reaper only closes sessions that are still stale when it looks.
    """

    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # These lists are ARQ's declarative worker API — the framework reads them as class
    # attributes, so the mutable-default lint does not apply.
    functions: ClassVar[list[Any]] = [
        session_reaper.run,
        league_scorer.run,
        push_notifier.run,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        # Runs a few minutes past each hour: fast enough that a forgotten timer never
        # blocks the next session for long, cheap enough to be unnoticeable.
        cron(session_reaper.run, minute=5, run_at_startup=False),
        # Hourly so in-progress weeks stay live; the run is idempotent, so the extra
        # passes just re-derive the same numbers.
        cron(league_scorer.run, minute=15, run_at_startup=False),
        # Every two minutes: a notification is only useful while it is fresh, and the run is
        # a no-op when nothing is pending.
        cron(push_notifier.run, second={0}, minute=set(range(0, 60, 2)), run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 300
