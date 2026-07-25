"""Study-session lifecycle: start, pause, resume, stop, manual entry, and offline sync.

Everything that changes session state funnels through here so there is one implementation
of the rules. Routers translate HTTP to these calls and nothing more.

Transactional model: each public method performs its reads and writes inside the caller's
session and commits once at the end. The "one running session per user" invariant is
enforced by a partial unique index, so a race between two devices fails at the database
rather than producing two live timers.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import ensure_utc
from app.core.errors import ConflictError, ErrorCode, NotFoundError, UnprocessableError
from app.domain.audit import record_audit
from app.domain.sessions.integrity import (
    IntegrityThresholds,
    IntegrityVerdict,
    SessionIntegrityInput,
    evaluate_session,
)
from app.domain.sessions.timeline import (
    TimelineEvent,
    TimelineResult,
    derive_timeline,
    validate_transition,
)
from app.models.enums import (
    ActorType,
    FocusMode,
    IntegrityStatus,
    SessionEventType,
    SessionSource,
    SessionStatus,
)
from app.models.study import StudySession, StudySessionEvent, Subject


class SyncOutcome:
    """Per-session result codes returned by the sync endpoint."""

    ACCEPTED = "accepted"
    MERGED = "merged"
    FLAGGED = "flagged"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    id: uuid.UUID
    sequence: int
    event_type: SessionEventType
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class IncomingSession:
    id: uuid.UUID
    subject_id: uuid.UUID
    events: tuple[IncomingEvent, ...]
    source: SessionSource = SessionSource.TIMER
    focus_mode: FocusMode = FocusMode.STOPWATCH
    pomodoro_focus_minutes: int | None = None
    note: str | None = None
    went_as_planned: bool | None = None
    client_created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SyncResult:
    session_id: uuid.UUID
    outcome: str
    status: SessionStatus
    duration_seconds: int
    integrity_status: IntegrityStatus
    reasons: tuple[str, ...] = ()
    message: str | None = None


class StudySessionService:
    """Domain service for the session lifecycle."""

    def __init__(self, db: AsyncSession, thresholds: IntegrityThresholds) -> None:
        self._db = db
        self._thresholds = thresholds

    # ------------------------------------------------------------------ queries

    async def get_owned(self, user_id: uuid.UUID, session_id: uuid.UUID) -> StudySession:
        """Fetch a session, scoping ownership in the query itself."""
        result = await self._db.execute(
            select(StudySession).where(
                StudySession.id == session_id, StudySession.user_id == user_id
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise NotFoundError(ErrorCode.SESSION_NOT_FOUND, "Study session not found.")
        return session

    async def get_running(self, user_id: uuid.UUID) -> StudySession | None:
        result = await self._db.execute(
            select(StudySession).where(
                StudySession.user_id == user_id,
                StudySession.status.in_([s.value for s in SessionStatus.running()]),
            )
        )
        return result.scalar_one_or_none()

    async def _require_subject(self, user_id: uuid.UUID, subject_id: uuid.UUID) -> Subject:
        result = await self._db.execute(
            select(Subject).where(Subject.id == subject_id, Subject.user_id == user_id)
        )
        subject = result.scalar_one_or_none()
        if subject is None:
            # 404 rather than 403: another user's subject must not be discoverable.
            raise NotFoundError(ErrorCode.SUBJECT_NOT_FOUND, "Subject not found.")
        return subject

    async def _load_events(self, session_id: uuid.UUID) -> list[StudySessionEvent]:
        result = await self._db.execute(
            select(StudySessionEvent)
            .where(StudySessionEvent.session_id == session_id)
            .order_by(StudySessionEvent.sequence)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------ lifecycle

    async def start(
        self,
        *,
        user_id: uuid.UUID,
        subject_id: uuid.UUID,
        now: datetime,
        session_id: uuid.UUID | None = None,
        focus_mode: FocusMode = FocusMode.STOPWATCH,
        pomodoro_focus_minutes: int | None = None,
        started_at: datetime | None = None,
        device_id: uuid.UUID | None = None,
    ) -> StudySession:
        """Begin a session. Fails if one is already running for this user."""
        await self._require_subject(user_id, subject_id)

        existing = await self.get_running(user_id)
        if existing is not None:
            raise ConflictError(
                ErrorCode.ACTIVE_SESSION_EXISTS,
                "You already have a running study session.",
                session_id=str(existing.id),
                status=existing.status,
            )

        begin = ensure_utc(started_at or now)
        session = StudySession(
            id=session_id or uuid.uuid4(),
            user_id=user_id,
            subject_id=subject_id,
            source=SessionSource.TIMER.value,
            status=SessionStatus.ACTIVE.value,
            focus_mode=focus_mode.value,
            pomodoro_focus_minutes=pomodoro_focus_minutes,
            started_at=begin,
            duration_seconds=0,
            integrity_status=IntegrityStatus.OK.value,
            integrity_reasons=[],
            device_id=device_id,
            client_created_at=begin,
        )
        session.events.append(
            StudySessionEvent(
                id=uuid.uuid4(),
                sequence=1,
                event_type=SessionEventType.START.value,
                occurred_at=begin,
                server_received_at=ensure_utc(now),
                payload={},
            )
        )
        self._db.add(session)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            # The partial unique index caught a concurrent start from another device.
            raise ConflictError(
                ErrorCode.ACTIVE_SESSION_EXISTS,
                "You already have a running study session.",
            ) from exc
        await self._db.refresh(session)
        return session

    async def transition(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        event_type: SessionEventType,
        now: datetime,
        occurred_at: datetime | None = None,
        note: str | None = None,
        went_as_planned: bool | None = None,
    ) -> StudySession:
        """Apply a pause/resume/stop event and recompute derived state."""
        session = await self.get_owned(user_id, session_id)
        current = SessionStatus(session.status)
        validate_transition(current, event_type)

        moment = ensure_utc(occurred_at or now)
        events = await self._load_events(session_id)
        next_sequence = max((event.sequence for event in events), default=0) + 1

        self._db.add(
            StudySessionEvent(
                id=uuid.uuid4(),
                session_id=session.id,
                sequence=next_sequence,
                event_type=event_type.value,
                occurred_at=moment,
                server_received_at=ensure_utc(now),
                payload={},
            )
        )
        await self._db.flush()

        timeline = derive_timeline(
            [_to_timeline_event(event) for event in await self._load_events(session_id)],
            now=now,
            strict=False,
        )
        await self._apply_timeline(
            session,
            timeline,
            now=now,
            note=note,
            went_as_planned=went_as_planned,
            evaluate=event_type is SessionEventType.STOP,
        )
        await self._db.commit()
        await self._db.refresh(session)
        return session

    async def create_manual(
        self,
        *,
        user_id: uuid.UUID,
        subject_id: uuid.UUID,
        started_at: datetime,
        ended_at: datetime,
        now: datetime,
        note: str | None = None,
    ) -> StudySession:
        """Record time the user is entering by hand.

        Stored, shown in personal statistics, and permanently marked as unverifiable — it
        earns no League Points (see docs/architecture/SECURITY.md).
        """
        await self._require_subject(user_id, subject_id)

        begin, end = ensure_utc(started_at), ensure_utc(ended_at)
        if end <= begin:
            raise UnprocessableError(
                ErrorCode.TIMELINE_INVALID, "The end time must be after the start time."
            )

        duration = int((end - begin).total_seconds())
        verdict = evaluate_session(
            SessionIntegrityInput(
                source=SessionSource.MANUAL,
                started_at=begin,
                ended_at=end,
                elapsed_seconds=duration,
                longest_interval_seconds=duration,
                server_received_at=ensure_utc(now),
            ),
            self._thresholds,
        )
        session = StudySession(
            id=uuid.uuid4(),
            user_id=user_id,
            subject_id=subject_id,
            source=SessionSource.MANUAL.value,
            status=SessionStatus.COMPLETED.value,
            focus_mode=FocusMode.STOPWATCH.value,
            started_at=begin,
            ended_at=end,
            duration_seconds=duration,
            note=note,
            integrity_status=verdict.status.value,
            integrity_reasons=[reason.value for reason in verdict.reasons],
            synced_at=ensure_utc(now),
        )
        self._db.add(session)
        await self._db.flush()
        await record_audit(
            self._db,
            actor_type=ActorType.USER,
            actor_id=user_id,
            action="session.manual_created",
            entity_type="study_session",
            entity_id=session.id,
            after={"duration_seconds": duration, "integrity_status": verdict.status.value},
            reason="Manual time entry",
            now=now,
        )
        await self._db.commit()
        await self._db.refresh(session)
        return session

    # ------------------------------------------------------------------ sync

    async def sync(
        self,
        *,
        user_id: uuid.UUID,
        sessions: Sequence[IncomingSession],
        now: datetime,
        device_id: uuid.UUID | None = None,
    ) -> list[SyncResult]:
        """Idempotently absorb sessions recorded offline.

        Replaying the same payload produces the same result and no duplicate rows: events
        are keyed by `(session_id, sequence)`, and a repeated sequence carrying *different*
        content flags the session instead of overwriting history.
        """
        results: list[SyncResult] = []
        for incoming in sessions:
            results.append(await self._sync_one(user_id, incoming, now, device_id))
        await self._db.commit()
        return results

    async def _sync_one(
        self,
        user_id: uuid.UUID,
        incoming: IncomingSession,
        now: datetime,
        device_id: uuid.UUID | None,
    ) -> SyncResult:
        if not incoming.events:
            return SyncResult(
                session_id=incoming.id,
                outcome=SyncOutcome.REJECTED,
                status=SessionStatus.DISCARDED,
                duration_seconds=0,
                integrity_status=IntegrityStatus.EXCLUDED,
                reasons=("no_events",),
                message="The session contained no timer events.",
            )

        subject = await self._require_subject(user_id, incoming.subject_id)

        existing = await self._db.get(StudySession, incoming.id)
        if existing is not None and existing.user_id != user_id:
            # A client tried to write into someone else's session id.
            raise NotFoundError(ErrorCode.SESSION_NOT_FOUND, "Study session not found.")

        merged = existing is not None
        session = existing or StudySession(
            id=incoming.id,
            user_id=user_id,
            subject_id=subject.id,
            source=incoming.source.value,
            status=SessionStatus.ACTIVE.value,
            focus_mode=incoming.focus_mode.value,
            pomodoro_focus_minutes=incoming.pomodoro_focus_minutes,
            started_at=ensure_utc(incoming.events[0].occurred_at),
            duration_seconds=0,
            integrity_reasons=[],
            device_id=device_id,
            client_created_at=(
                ensure_utc(incoming.client_created_at) if incoming.client_created_at else None
            ),
        )
        if existing is None:
            self._db.add(session)
            await self._db.flush()

        known = {event.sequence: event for event in await self._load_events(session.id)}
        conflict = False
        appended = 0

        for event in sorted(incoming.events, key=lambda item: item.sequence):
            prior = known.get(event.sequence)
            if prior is not None:
                # Same slot seen before: identical is a no-op, different is a conflict we
                # record rather than resolve — overwriting history would destroy evidence.
                if prior.event_type != event.event_type.value or ensure_utc(
                    prior.occurred_at
                ) != ensure_utc(event.occurred_at):
                    conflict = True
                continue
            self._db.add(
                StudySessionEvent(
                    id=event.id,
                    session_id=session.id,
                    sequence=event.sequence,
                    event_type=event.event_type.value,
                    occurred_at=ensure_utc(event.occurred_at),
                    server_received_at=ensure_utc(now),
                    payload={"offline_sync": True},
                )
            )
            appended += 1

        await self._db.flush()

        timeline = derive_timeline(
            [_to_timeline_event(event) for event in await self._load_events(session.id)],
            now=now,
            strict=False,
        )
        overlaps = await self._overlaps_existing(user_id, session.id, timeline)
        verdict = await self._apply_timeline(
            session,
            timeline,
            now=now,
            note=incoming.note,
            went_as_planned=incoming.went_as_planned,
            evaluate=True,
            overlaps=overlaps,
            has_event_conflict=conflict,
        )
        session.synced_at = ensure_utc(now)
        if device_id is not None:
            session.device_id = device_id

        if appended or conflict:
            await record_audit(
                self._db,
                actor_type=ActorType.USER,
                actor_id=user_id,
                action="session.synced",
                entity_type="study_session",
                entity_id=session.id,
                after={
                    "events_appended": appended,
                    "duration_seconds": session.duration_seconds,
                    "integrity_status": session.integrity_status,
                    "conflict": conflict,
                },
                reason="Offline synchronisation",
                now=now,
            )

        if conflict:
            outcome = SyncOutcome.FLAGGED
        elif merged:
            outcome = SyncOutcome.MERGED
        elif verdict.status is not IntegrityStatus.OK:
            outcome = SyncOutcome.FLAGGED
        else:
            outcome = SyncOutcome.ACCEPTED

        messages = verdict.messages()
        return SyncResult(
            session_id=session.id,
            outcome=outcome,
            status=SessionStatus(session.status),
            duration_seconds=session.duration_seconds,
            integrity_status=verdict.status,
            reasons=tuple(reason.value for reason in verdict.reasons),
            message=messages[0] if messages else None,
        )

    # ------------------------------------------------------------------ helpers

    async def _overlaps_existing(
        self, user_id: uuid.UUID, session_id: uuid.UUID, timeline: TimelineResult
    ) -> bool:
        """True when this session's span intersects another verified session."""
        end = timeline.ended_at
        if end is None:
            return False
        result = await self._db.execute(
            select(StudySession.id).where(
                StudySession.user_id == user_id,
                StudySession.id != session_id,
                StudySession.source == SessionSource.TIMER.value,
                StudySession.status == SessionStatus.COMPLETED.value,
                StudySession.ended_at.is_not(None),
                or_(
                    and_(
                        StudySession.started_at < end,
                        StudySession.ended_at > timeline.started_at,
                    )
                ),
            )
        )
        return result.first() is not None

    async def _apply_timeline(
        self,
        session: StudySession,
        timeline: TimelineResult,
        *,
        now: datetime,
        note: str | None,
        went_as_planned: bool | None,
        evaluate: bool,
        overlaps: bool = False,
        has_event_conflict: bool = False,
    ) -> IntegrityVerdict:
        """Write derived state back onto the session row."""
        session.status = timeline.status.value
        session.started_at = timeline.started_at
        session.ended_at = timeline.ended_at
        session.duration_seconds = timeline.elapsed_seconds
        session.version += 1
        if note is not None:
            session.note = note
        if went_as_planned is not None:
            session.went_as_planned = went_as_planned

        if not evaluate:
            return IntegrityVerdict(IntegrityStatus(session.integrity_status), ())

        events = await self._load_events(session.id)
        latest_event_at = max((ensure_utc(e.occurred_at) for e in events), default=None)
        verdict = evaluate_session(
            SessionIntegrityInput(
                source=SessionSource(session.source),
                started_at=timeline.started_at,
                ended_at=timeline.ended_at,
                elapsed_seconds=timeline.elapsed_seconds,
                longest_interval_seconds=timeline.longest_interval_seconds,
                timeline_problems=timeline.problems,
                latest_event_at=latest_event_at,
                server_received_at=ensure_utc(now),
                overlaps_existing=overlaps,
                has_event_conflict=has_event_conflict,
            ),
            self._thresholds,
        )
        previous_status = session.integrity_status
        session.integrity_status = verdict.status.value
        session.integrity_reasons = [reason.value for reason in verdict.reasons]

        if verdict.status is not IntegrityStatus.OK and previous_status != verdict.status.value:
            await record_audit(
                self._db,
                actor_type=ActorType.SYSTEM,
                actor_id=None,
                action="session.integrity_flagged",
                entity_type="study_session",
                entity_id=session.id,
                before={"integrity_status": previous_status},
                after={
                    "integrity_status": verdict.status.value,
                    "reasons": [reason.value for reason in verdict.reasons],
                },
                reason="Automatic integrity evaluation",
                now=now,
            )
        return verdict


def _to_timeline_event(event: StudySessionEvent) -> TimelineEvent:
    return TimelineEvent(
        sequence=event.sequence,
        event_type=SessionEventType(event.event_type),
        occurred_at=ensure_utc(event.occurred_at),
    )
