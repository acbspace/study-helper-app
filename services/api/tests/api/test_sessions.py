"""Study-session lifecycle against the database and HTTP layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.domain.sessions.service import StudySessionService
from app.models.enums import IntegrityStatus, SessionEventType, SessionStatus
from app.models.study import StudySession, StudySessionEvent, Subject
from app.models.user import User

NOW = datetime(2026, 7, 22, 9, 0, tzinfo=UTC)


class TestStart:
    async def test_start_creates_an_active_session_with_a_start_event(
        self, sessions_service: StudySessionService, user: User, subject: Subject, db: AsyncSession
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        assert session.status == SessionStatus.ACTIVE.value
        assert session.duration_seconds == 0

        events = (
            (
                await db.execute(
                    select(StudySessionEvent).where(StudySessionEvent.session_id == session.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].event_type == SessionEventType.START.value
        assert events[0].sequence == 1

    async def test_a_second_start_is_rejected(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        """Two live timers would make study time meaningless."""
        first = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        with pytest.raises(AppError) as exc_info:
            await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        assert exc_info.value.code.value == "active_session_exists"
        assert exc_info.value.details["session_id"] == str(first.id)

    async def test_starting_after_stopping_is_allowed(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        first = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        await sessions_service.transition(
            user_id=user.id,
            session_id=first.id,
            event_type=SessionEventType.STOP,
            now=NOW + timedelta(minutes=30),
        )
        second = await sessions_service.start(
            user_id=user.id, subject_id=subject.id, now=NOW + timedelta(hours=1)
        )
        assert second.status == SessionStatus.ACTIVE.value

    async def test_cannot_start_on_another_users_subject(
        self, sessions_service: StudySessionService, user: User, other_subject: Subject
    ) -> None:
        with pytest.raises(AppError) as exc_info:
            await sessions_service.start(user_id=user.id, subject_id=other_subject.id, now=NOW)
        assert exc_info.value.status_code == 404
        assert exc_info.value.code.value == "subject_not_found"

    async def test_two_users_can_study_simultaneously(
        self,
        sessions_service: StudySessionService,
        user: User,
        other_user: User,
        subject: Subject,
        other_subject: Subject,
    ) -> None:
        """The one-session limit is per user, not global."""
        await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        second = await sessions_service.start(
            user_id=other_user.id, subject_id=other_subject.id, now=NOW
        )
        assert second.status == SessionStatus.ACTIVE.value


class TestPauseResumeStop:
    async def test_pause_freezes_elapsed_time(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        paused = await sessions_service.transition(
            user_id=user.id,
            session_id=session.id,
            event_type=SessionEventType.PAUSE,
            now=NOW + timedelta(minutes=25),
        )
        assert paused.status == SessionStatus.PAUSED.value
        assert paused.duration_seconds == 25 * 60

    async def test_paused_time_is_not_counted(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        await sessions_service.transition(
            user_id=user.id,
            session_id=session.id,
            event_type=SessionEventType.PAUSE,
            now=NOW + timedelta(minutes=25),
        )
        await sessions_service.transition(
            user_id=user.id,
            session_id=session.id,
            event_type=SessionEventType.RESUME,
            now=NOW + timedelta(minutes=55),
        )
        stopped = await sessions_service.transition(
            user_id=user.id,
            session_id=session.id,
            event_type=SessionEventType.STOP,
            now=NOW + timedelta(minutes=70),
        )
        # 25 studied + 30 paused + 15 studied = 40 minutes of study.
        assert stopped.duration_seconds == 40 * 60
        assert stopped.status == SessionStatus.COMPLETED.value

    async def test_stop_records_note_and_plan_marker(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        stopped = await sessions_service.transition(
            user_id=user.id,
            session_id=session.id,
            event_type=SessionEventType.STOP,
            now=NOW + timedelta(minutes=50),
            note="Finished chapter 4",
            went_as_planned=True,
        )
        assert stopped.note == "Finished chapter 4"
        assert stopped.went_as_planned is True
        assert stopped.integrity_status == IntegrityStatus.OK.value

    async def test_illegal_transitions_are_rejected(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        with pytest.raises(AppError) as exc_info:
            await sessions_service.transition(
                user_id=user.id,
                session_id=session.id,
                event_type=SessionEventType.RESUME,
                now=NOW + timedelta(minutes=5),
            )
        assert exc_info.value.code.value == "invalid_transition"

    async def test_completed_sessions_cannot_be_restarted(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        await sessions_service.transition(
            user_id=user.id,
            session_id=session.id,
            event_type=SessionEventType.STOP,
            now=NOW + timedelta(minutes=30),
        )
        with pytest.raises(AppError):
            await sessions_service.transition(
                user_id=user.id,
                session_id=session.id,
                event_type=SessionEventType.RESUME,
                now=NOW + timedelta(minutes=40),
            )

    async def test_cannot_control_another_users_session(
        self,
        sessions_service: StudySessionService,
        user: User,
        other_user: User,
        subject: Subject,
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        with pytest.raises(AppError) as exc_info:
            await sessions_service.transition(
                user_id=other_user.id,
                session_id=session.id,
                event_type=SessionEventType.STOP,
                now=NOW + timedelta(minutes=10),
            )
        assert exc_info.value.status_code == 404


class TestManualEntry:
    async def test_manual_time_is_stored_but_excluded_from_competition(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        session = await sessions_service.create_manual(
            user_id=user.id,
            subject_id=subject.id,
            started_at=NOW - timedelta(hours=2),
            ended_at=NOW - timedelta(hours=1),
            now=NOW,
        )
        assert session.duration_seconds == 3600
        assert session.source == "manual"
        assert session.integrity_status == IntegrityStatus.EXCLUDED.value
        assert "manual_entry" in session.integrity_reasons

    async def test_manual_entry_writes_an_audit_record(
        self, sessions_service: StudySessionService, user: User, subject: Subject, db: AsyncSession
    ) -> None:
        from app.models.platform import AuditLog

        await sessions_service.create_manual(
            user_id=user.id,
            subject_id=subject.id,
            started_at=NOW - timedelta(hours=2),
            ended_at=NOW - timedelta(hours=1),
            now=NOW,
        )
        entries = (
            (await db.execute(select(AuditLog).where(AuditLog.action == "session.manual_created")))
            .scalars()
            .all()
        )
        assert len(entries) == 1

    async def test_backwards_time_range_is_rejected(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        with pytest.raises(AppError):
            await sessions_service.create_manual(
                user_id=user.id,
                subject_id=subject.id,
                started_at=NOW,
                ended_at=NOW - timedelta(hours=1),
                now=NOW,
            )

    async def test_manual_entry_does_not_block_the_timer(
        self, sessions_service: StudySessionService, user: User, subject: Subject
    ) -> None:
        """Manual sessions are already complete, so they never occupy the running slot."""
        await sessions_service.create_manual(
            user_id=user.id,
            subject_id=subject.id,
            started_at=NOW - timedelta(hours=2),
            ended_at=NOW - timedelta(hours=1),
            now=NOW,
        )
        live = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        assert live.status == SessionStatus.ACTIVE.value


class TestHttpEndpoints:
    async def test_full_timer_flow_over_http(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        created = await client.post(
            "/subjects", json={"name": "Physics", "color_hex": "#37B27A"}, headers=auth_headers
        )
        assert created.status_code == 201
        subject_id = created.json()["id"]

        started = await client.post(
            "/study-sessions/start", json={"subject_id": subject_id}, headers=auth_headers
        )
        assert started.status_code == 201
        session_id = started.json()["id"]

        active = await client.get("/study-sessions/active", headers=auth_headers)
        assert active.json()["id"] == session_id

        paused = await client.post(
            f"/study-sessions/{session_id}/pause", json={}, headers=auth_headers
        )
        assert paused.json()["status"] == "paused"

        resumed = await client.post(
            f"/study-sessions/{session_id}/resume", json={}, headers=auth_headers
        )
        assert resumed.json()["status"] == "active"

        stopped = await client.post(
            f"/study-sessions/{session_id}/stop",
            json={"note": "done", "went_as_planned": True},
            headers=auth_headers,
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "completed"

        assert (await client.get("/study-sessions/active", headers=auth_headers)).json() is None

    async def test_conflict_returns_a_stable_error_code(
        self, client: AsyncClient, auth_headers: dict[str, str], subject: Subject
    ) -> None:
        payload = {"subject_id": str(subject.id)}
        await client.post("/study-sessions/start", json=payload, headers=auth_headers)
        second = await client.post("/study-sessions/start", json=payload, headers=auth_headers)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "active_session_exists"

    async def test_unauthenticated_requests_are_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/study-sessions/active")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"

    async def test_another_users_session_is_not_found(
        self,
        client: AsyncClient,
        other_auth_headers: dict[str, str],
        sessions_service: StudySessionService,
        user: User,
        subject: Subject,
    ) -> None:
        session = await sessions_service.start(user_id=user.id, subject_id=subject.id, now=NOW)
        response = await client.post(
            f"/study-sessions/{session.id}/stop", json={}, headers=other_auth_headers
        )
        assert response.status_code == 404

    async def test_unknown_session_id_is_not_found(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            f"/study-sessions/{uuid.uuid4()}/pause", json={}, headers=auth_headers
        )
        assert response.status_code == 404


class TestDatabaseInvariants:
    async def test_partial_unique_index_blocks_a_second_running_session(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        """Defence in depth: even bypassing the service, the database refuses."""
        from sqlalchemy.exc import IntegrityError

        for _ in range(2):
            db.add(
                StudySession(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    subject_id=subject.id,
                    status=SessionStatus.ACTIVE.value,
                    started_at=NOW,
                    integrity_reasons=[],
                )
            )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_duplicate_event_sequence_is_rejected(
        self, db: AsyncSession, user: User, subject: Subject
    ) -> None:
        from sqlalchemy.exc import IntegrityError

        session = StudySession(
            id=uuid.uuid4(),
            user_id=user.id,
            subject_id=subject.id,
            status=SessionStatus.ACTIVE.value,
            started_at=NOW,
            integrity_reasons=[],
        )
        db.add(session)
        await db.commit()

        for _ in range(2):
            db.add(
                StudySessionEvent(
                    id=uuid.uuid4(),
                    session_id=session.id,
                    sequence=1,
                    event_type=SessionEventType.START.value,
                    occurred_at=NOW,
                    server_received_at=NOW,
                    payload={},
                )
            )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
