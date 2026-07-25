"""Offline synchronisation: idempotency is the whole point."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.sessions.service import (
    IncomingEvent,
    IncomingSession,
    StudySessionService,
    SyncOutcome,
)
from app.models.enums import IntegrityStatus, SessionEventType, SessionStatus
from app.models.study import StudySession, StudySessionEvent, Subject
from app.models.user import User

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
STUDIED_AT = NOW - timedelta(hours=2)


def offline_session(
    subject_id: uuid.UUID,
    *,
    session_id: uuid.UUID | None = None,
    minutes: int = 50,
    include_stop: bool = True,
) -> IncomingSession:
    """A session recorded on a device with no network."""
    events = [
        IncomingEvent(uuid.uuid4(), 1, SessionEventType.START, STUDIED_AT),
    ]
    if include_stop:
        events.append(
            IncomingEvent(
                uuid.uuid4(), 2, SessionEventType.STOP, STUDIED_AT + timedelta(minutes=minutes)
            )
        )
    return IncomingSession(
        id=session_id or uuid.uuid4(),
        subject_id=subject_id,
        events=tuple(events),
        client_created_at=STUDIED_AT,
    )


class TestIdempotency:
    async def test_replaying_the_same_payload_changes_nothing(
        self, sessions_service: StudySessionService, user: User, subject: Subject, db: AsyncSession
    ) -> None:
        """The core offline guarantee: a client may retry as often as it likes."""
        payload = [offline_session(subject.id)]

        first = await sessions_service.sync(user_id=user.id, sessions=payload, now=NOW)
        second = await sessions_service.sync(user_id=user.id, sessions=payload, now=NOW)
        third = await sessions_service.sync(user_id=user.id, sessions=payload, now=NOW)

        assert first[0].outcome == SyncOutcome.ACCEPTED
        assert second[0].outcome == SyncOutcome.MERGED
        assert third[0].outcome == SyncOutcome.MERGED
        assert first[0].duration_seconds == second[0].duration_seconds == 50 * 60

        session_count = await db.scalar(
            select(func.count()).select_from(StudySession).where(StudySession.user_id == user.id)
        )
        event_count = await db.scalar(select(func.count()).select_from(StudySessionEvent))
        assert session_count == 1
        assert event_count == 2

    async def test_duplicate_events_within_a_session_are_not_appended(
        self, sessions_service: StudySessionService, user: User, subject: Subject, db: AsyncSession
    ) -> None:
        session_id = uuid.uuid4()
        start_event = IncomingEvent(uuid.uuid4(), 1, SessionEventType.START, STUDIED_AT)

        await sessions_service.sync(
            user_id=user.id,
            sessions=[IncomingSession(id=session_id, subject_id=subject.id, events=(start_event,))],
            now=NOW,
        )
        # Later batch re-sends the start event plus the stop event.
        await sessions_service.sync(
            user_id=user.id,
            sessions=[
                IncomingSession(
                    id=session_id,
                    subject_id=subject.id,
                    events=(
                        start_event,
                        IncomingEvent(
                            uuid.uuid4(),
                            2,
                            SessionEventType.STOP,
                            STUDIED_AT + timedelta(minutes=30),
                        ),
                    ),
                )
            ],
            now=NOW,
        )
        events = await db.scalar(select(func.count()).select_from(StudySessionEvent))
        assert events == 2

    async def test_incremental_sync_extends_an_existing_session(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        session_id = uuid.uuid4()
        await sessions_service.sync(
            user_id=user.id,
            sessions=[offline_session(subject.id, session_id=session_id, include_stop=False)],
            now=NOW,
        )
        results = await sessions_service.sync(
            user_id=user.id,
            sessions=[offline_session(subject.id, session_id=session_id, minutes=45)],
            now=NOW,
        )
        assert results[0].status is SessionStatus.COMPLETED
        assert results[0].duration_seconds == 45 * 60


class TestConflictHandling:
    async def test_conflicting_event_content_flags_rather_than_overwrites(
        self, sessions_service: StudySessionService, user: User, subject: Subject, db: AsyncSession
    ) -> None:
        """Rewriting history would destroy the evidence; we keep the original and flag."""
        session_id = uuid.uuid4()
        original = IncomingEvent(uuid.uuid4(), 1, SessionEventType.START, STUDIED_AT)
        await sessions_service.sync(
            user_id=user.id,
            sessions=[IncomingSession(id=session_id, subject_id=subject.id, events=(original,))],
            now=NOW,
        )

        tampered = IncomingEvent(
            uuid.uuid4(), 1, SessionEventType.START, STUDIED_AT - timedelta(hours=5)
        )
        results = await sessions_service.sync(
            user_id=user.id,
            sessions=[IncomingSession(id=session_id, subject_id=subject.id, events=(tampered,))],
            now=NOW,
        )

        assert results[0].outcome == SyncOutcome.FLAGGED
        assert "event_conflict" in results[0].reasons

        stored = await db.get(StudySessionEvent, original.id)
        assert stored is not None  # original event untouched

    async def test_overlapping_sessions_are_flagged_but_kept(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        first = offline_session(subject.id, minutes=60)
        await sessions_service.sync(user_id=user.id, sessions=[first], now=NOW)

        overlapping = IncomingSession(
            id=uuid.uuid4(),
            subject_id=subject.id,
            events=(
                IncomingEvent(
                    uuid.uuid4(), 1, SessionEventType.START, STUDIED_AT + timedelta(minutes=30)
                ),
                IncomingEvent(
                    uuid.uuid4(), 2, SessionEventType.STOP, STUDIED_AT + timedelta(minutes=90)
                ),
            ),
        )
        results = await sessions_service.sync(user_id=user.id, sessions=[overlapping], now=NOW)

        assert results[0].outcome == SyncOutcome.FLAGGED
        assert "overlapping_session" in results[0].reasons
        # Kept, not deleted — the user still sees the time in personal statistics.
        assert results[0].duration_seconds == 60 * 60
        assert results[0].message is not None

    async def test_broken_timeline_is_stored_and_flagged_not_discarded(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        broken = IncomingSession(
            id=uuid.uuid4(),
            subject_id=subject.id,
            events=(
                IncomingEvent(uuid.uuid4(), 1, SessionEventType.START, STUDIED_AT),
                IncomingEvent(uuid.uuid4(), 2, SessionEventType.RESUME, STUDIED_AT),
                IncomingEvent(
                    uuid.uuid4(), 3, SessionEventType.STOP, STUDIED_AT + timedelta(minutes=30)
                ),
            ),
        )
        results = await sessions_service.sync(user_id=user.id, sessions=[broken], now=NOW)
        assert results[0].integrity_status is IntegrityStatus.FLAGGED
        assert "timeline_invalid" in results[0].reasons

    async def test_empty_event_list_is_rejected_cleanly(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        results = await sessions_service.sync(
            user_id=user.id,
            sessions=[IncomingSession(id=uuid.uuid4(), subject_id=subject.id, events=())],
            now=NOW,
        )
        assert results[0].outcome == SyncOutcome.REJECTED


class TestAuthorization:
    async def test_cannot_sync_into_another_users_subject(
        self, sessions_service: StudySessionService, user: User, other_subject: Subject
    ) -> None:
        import pytest

        from app.core.errors import AppError

        with pytest.raises(AppError) as exc_info:
            await sessions_service.sync(
                user_id=user.id, sessions=[offline_session(other_subject.id)], now=NOW
            )
        assert exc_info.value.status_code == 404

    async def test_cannot_overwrite_another_users_session(
        self,
        sessions_service: StudySessionService,
        user: User,
        other_user: User,
        subject: Subject,
        other_subject: Subject,
    ) -> None:
        import pytest

        from app.core.errors import AppError

        mine = offline_session(subject.id)
        await sessions_service.sync(user_id=user.id, sessions=[mine], now=NOW)

        # The rival guesses the session id and tries to write to it.
        attack = IncomingSession(
            id=mine.id,
            subject_id=other_subject.id,
            events=(IncomingEvent(uuid.uuid4(), 9, SessionEventType.STOP, NOW),),
        )
        with pytest.raises(AppError) as exc_info:
            await sessions_service.sync(user_id=other_user.id, sessions=[attack], now=NOW)
        assert exc_info.value.status_code == 404


class TestSyncOverHttp:
    async def test_sync_endpoint_returns_per_session_results(
        self, client: AsyncClient, auth_headers: dict[str, str], subject: Subject
    ) -> None:
        session_id = str(uuid.uuid4())
        # This test drives the real endpoint, which stamps integrity against the live server
        # clock — so the session must be recent, not a fixed date that ages past the
        # retro-edit window. (The service-level tests inject now=NOW and stay date-independent.)
        recent_start = datetime.now(UTC) - timedelta(hours=1)
        payload = {
            "sessions": [
                {
                    "id": session_id,
                    "subject_id": str(subject.id),
                    "events": [
                        {
                            "id": str(uuid.uuid4()),
                            "sequence": 1,
                            "event_type": "start",
                            "occurred_at": recent_start.isoformat(),
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "sequence": 2,
                            "event_type": "stop",
                            "occurred_at": (recent_start + timedelta(minutes=45)).isoformat(),
                        },
                    ],
                }
            ]
        }
        response = await client.post("/study-sessions/sync", json=payload, headers=auth_headers)
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["session_id"] == session_id
        assert result["outcome"] == "accepted"
        assert result["duration_seconds"] == 45 * 60

        # Retrying the exact request is safe.
        again = await client.post("/study-sessions/sync", json=payload, headers=auth_headers)
        assert again.json()["results"][0]["duration_seconds"] == 45 * 60

    async def test_duplicate_sequences_in_one_batch_are_rejected_by_validation(
        self, client: AsyncClient, auth_headers: dict[str, str], subject: Subject
    ) -> None:
        event = {
            "id": str(uuid.uuid4()),
            "sequence": 1,
            "event_type": "start",
            "occurred_at": STUDIED_AT.isoformat(),
        }
        payload = {
            "sessions": [
                {
                    "id": str(uuid.uuid4()),
                    "subject_id": str(subject.id),
                    "events": [event, {**event, "id": str(uuid.uuid4())}],
                }
            ]
        }
        response = await client.post("/study-sessions/sync", json=payload, headers=auth_headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
