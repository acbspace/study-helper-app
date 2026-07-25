"""Close abandoned study sessions.

A phone can die mid-session, or a user can simply forget to press stop. Without this job
the session stays "running" forever: it blocks the next session (one-running-session
invariant) and would eventually be counted as an implausible marathon.

The reaper closes such sessions at their last known event rather than at discovery time,
so a forgotten timer never inflates study time, and marks them so the user can see what
happened. Every close is written to the audit log.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.clock import ensure_utc, utc_now
from app.core.logging import get_logger
from app.domain.audit import record_audit
from app.domain.sessions.integrity import IntegrityReason
from app.domain.sessions.timeline import TimelineEvent, derive_timeline
from app.models.enums import (
    ActorType,
    IntegrityStatus,
    SessionEventType,
    SessionStatus,
)
from app.models.study import StudySession, StudySessionEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReaperResult:
    inspected: int
    closed: int
    session_ids: tuple[uuid.UUID, ...]


async def reap_stale_sessions(
    db: AsyncSession, *, now: datetime | None = None, max_age_hours: float = 12.0
) -> ReaperResult:
    """Close running sessions whose last event is older than `max_age_hours`."""
    moment = ensure_utc(now or utc_now())
    cutoff = moment - timedelta(hours=max_age_hours)

    result = await db.execute(
        select(StudySession).where(
            StudySession.status.in_([status.value for status in SessionStatus.running()]),
            StudySession.started_at < cutoff,
        )
    )
    candidates = list(result.scalars().all())
    closed: list[uuid.UUID] = []

    for session in candidates:
        events = list(
            (
                await db.execute(
                    select(StudySessionEvent)
                    .where(StudySessionEvent.session_id == session.id)
                    .order_by(StudySessionEvent.sequence)
                )
            )
            .scalars()
            .all()
        )
        if not events:  # pragma: no cover - a session always has a start event
            continue

        last_event_at = max(ensure_utc(event.occurred_at) for event in events)
        if last_event_at >= cutoff:
            # Still active recently (e.g. paused then resumed): leave it alone.
            continue

        # Stop at the last known activity, never at "now" — the user was not studying
        # for the hours in between, and crediting that time would be a lie.
        stop_sequence = max(event.sequence for event in events) + 1
        db.add(
            StudySessionEvent(
                id=uuid.uuid4(),
                session_id=session.id,
                sequence=stop_sequence,
                event_type=SessionEventType.STOP.value,
                occurred_at=last_event_at,
                server_received_at=moment,
                payload={"auto_closed": True, "reason": "stale_session"},
            )
        )
        await db.flush()

        timeline_events = [
            TimelineEvent(
                sequence=event.sequence,
                event_type=SessionEventType(event.event_type),
                occurred_at=ensure_utc(event.occurred_at),
            )
            for event in events
        ]
        timeline_events.append(TimelineEvent(stop_sequence, SessionEventType.STOP, last_event_at))
        timeline = derive_timeline(timeline_events, now=moment, strict=False)

        previous_status = session.status
        session.status = SessionStatus.COMPLETED.value
        session.ended_at = timeline.ended_at
        session.duration_seconds = timeline.elapsed_seconds
        session.integrity_status = IntegrityStatus.FLAGGED.value
        session.integrity_reasons = [IntegrityReason.MARATHON_SESSION.value]
        session.version += 1

        await record_audit(
            db,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            action="session.auto_closed",
            entity_type="study_session",
            entity_id=session.id,
            before={"status": previous_status},
            after={
                "status": session.status,
                "duration_seconds": session.duration_seconds,
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            },
            reason=f"No activity for more than {max_age_hours} hours",
            now=moment,
        )
        closed.append(session.id)

    await db.commit()
    logger.info("session_reaper_finished", inspected=len(candidates), closed=len(closed))
    return ReaperResult(inspected=len(candidates), closed=len(closed), session_ids=tuple(closed))


async def run(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ entry point."""
    factory = ctx["session_factory"]
    async with factory() as db:
        result = await reap_stale_sessions(db, max_age_hours=ctx["settings"].max_session_hours)
    return {"inspected": result.inspected, "closed": result.closed}
