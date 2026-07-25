"""Study-session routes.

State changes are verb sub-resources rather than PATCHes because each one is a command
with rules (see docs/api/API_CONVENTIONS.md).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DeviceDep, SessionServiceDep
from app.core.clock import utc_now
from app.domain.sessions.service import IncomingEvent, IncomingSession
from app.models.enums import SessionEventType
from app.schemas.sessions import (
    ManualSessionRequest,
    SessionResponse,
    StartSessionRequest,
    StopSessionRequest,
    SyncRequest,
    SyncResponse,
    SyncResultResponse,
    TransitionRequest,
)

router = APIRouter(prefix="/study-sessions", tags=["study-sessions"])


@router.get("/active", response_model=SessionResponse | None, summary="Current running session")
async def get_active_session(
    user: CurrentUser, sessions: SessionServiceDep
) -> SessionResponse | None:
    """Used by the app on launch to reconcile a locally restored timer with the server."""
    session = await sessions.get_running(user.id)
    return SessionResponse.model_validate(session) if session else None


@router.post(
    "/start",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a session",
)
async def start_session(
    payload: StartSessionRequest,
    user: CurrentUser,
    sessions: SessionServiceDep,
    device_id: DeviceDep,
) -> SessionResponse:
    session = await sessions.start(
        user_id=user.id,
        subject_id=payload.subject_id,
        session_id=payload.session_id,
        focus_mode=payload.focus_mode,
        pomodoro_focus_minutes=payload.pomodoro_focus_minutes,
        started_at=payload.started_at,
        device_id=device_id,
        now=utc_now(),
    )
    return SessionResponse.model_validate(session)


@router.post("/{session_id}/pause", response_model=SessionResponse, summary="Pause a session")
async def pause_session(
    session_id: uuid.UUID,
    payload: TransitionRequest,
    user: CurrentUser,
    sessions: SessionServiceDep,
) -> SessionResponse:
    session = await sessions.transition(
        user_id=user.id,
        session_id=session_id,
        event_type=SessionEventType.PAUSE,
        occurred_at=payload.occurred_at,
        now=utc_now(),
    )
    return SessionResponse.model_validate(session)


@router.post("/{session_id}/resume", response_model=SessionResponse, summary="Resume a session")
async def resume_session(
    session_id: uuid.UUID,
    payload: TransitionRequest,
    user: CurrentUser,
    sessions: SessionServiceDep,
) -> SessionResponse:
    session = await sessions.transition(
        user_id=user.id,
        session_id=session_id,
        event_type=SessionEventType.RESUME,
        occurred_at=payload.occurred_at,
        now=utc_now(),
    )
    return SessionResponse.model_validate(session)


@router.post("/{session_id}/stop", response_model=SessionResponse, summary="Stop a session")
async def stop_session(
    session_id: uuid.UUID,
    payload: StopSessionRequest,
    user: CurrentUser,
    sessions: SessionServiceDep,
) -> SessionResponse:
    session = await sessions.transition(
        user_id=user.id,
        session_id=session_id,
        event_type=SessionEventType.STOP,
        occurred_at=payload.occurred_at,
        note=payload.note,
        went_as_planned=payload.went_as_planned,
        now=utc_now(),
    )
    return SessionResponse.model_validate(session)


@router.post(
    "/manual",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add time manually",
)
async def create_manual_session(
    payload: ManualSessionRequest, user: CurrentUser, sessions: SessionServiceDep
) -> SessionResponse:
    """Manual time is kept and shown, but never earns League Points."""
    session = await sessions.create_manual(
        user_id=user.id,
        subject_id=payload.subject_id,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        note=payload.note,
        now=utc_now(),
    )
    return SessionResponse.model_validate(session)


@router.post("/sync", response_model=SyncResponse, summary="Synchronise offline sessions")
async def sync_sessions(
    payload: SyncRequest,
    user: CurrentUser,
    sessions: SessionServiceDep,
    device_id: DeviceDep,
) -> SyncResponse:
    """Idempotent batch upload. Replaying a payload changes nothing and returns the same
    result, so clients can retry freely."""
    incoming = [
        IncomingSession(
            id=item.id,
            subject_id=item.subject_id,
            source=item.source,
            focus_mode=item.focus_mode,
            pomodoro_focus_minutes=item.pomodoro_focus_minutes,
            note=item.note,
            went_as_planned=item.went_as_planned,
            client_created_at=item.client_created_at,
            events=tuple(
                IncomingEvent(
                    id=event.id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    occurred_at=event.occurred_at,
                )
                for event in item.events
            ),
        )
        for item in payload.sessions
    ]
    results = await sessions.sync(
        user_id=user.id, sessions=incoming, device_id=device_id, now=utc_now()
    )
    return SyncResponse(
        results=[
            SyncResultResponse(
                session_id=result.session_id,
                outcome=result.outcome,
                status=result.status,
                duration_seconds=result.duration_seconds,
                integrity_status=result.integrity_status.value,
                reasons=list(result.reasons),
                message=result.message,
            )
            for result in results
        ]
    )
