"""Study-session contracts, including the offline sync payload."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.models.enums import FocusMode, SessionEventType, SessionSource, SessionStatus
from app.schemas.common import ResponseModel, StrictModel


class SessionResponse(ResponseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    source: SessionSource
    status: SessionStatus
    focus_mode: FocusMode
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int
    note: str | None
    went_as_planned: bool | None
    integrity_status: str
    integrity_reasons: list[str]
    synced_at: datetime | None


class StartSessionRequest(StrictModel):
    subject_id: uuid.UUID
    # The client may supply the id so an optimistically-started local session keeps its
    # identity once the network call lands.
    session_id: uuid.UUID | None = None
    focus_mode: FocusMode = FocusMode.STOPWATCH
    pomodoro_focus_minutes: int | None = Field(default=None, ge=1, le=180)
    started_at: datetime | None = None


class TransitionRequest(StrictModel):
    occurred_at: datetime | None = None


class StopSessionRequest(StrictModel):
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    went_as_planned: bool | None = None


class ManualSessionRequest(StrictModel):
    subject_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_order(self) -> ManualSessionRequest:
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be after started_at")
        return self


class SyncEvent(StrictModel):
    id: uuid.UUID
    sequence: int = Field(ge=1)
    event_type: SessionEventType
    occurred_at: datetime


class SyncSession(StrictModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    events: list[SyncEvent] = Field(min_length=1, max_length=500)
    source: SessionSource = SessionSource.TIMER
    focus_mode: FocusMode = FocusMode.STOPWATCH
    pomodoro_focus_minutes: int | None = Field(default=None, ge=1, le=180)
    note: str | None = Field(default=None, max_length=500)
    went_as_planned: bool | None = None
    client_created_at: datetime | None = None

    @field_validator("events")
    @classmethod
    def _unique_sequences(cls, events: list[SyncEvent]) -> list[SyncEvent]:
        """A batch that contradicts itself is a client bug, not a server decision."""
        sequences = [event.sequence for event in events]
        if len(set(sequences)) != len(sequences):
            raise ValueError("event sequences must be unique within a session")
        return events


class SyncRequest(StrictModel):
    sessions: list[SyncSession] = Field(min_length=1, max_length=100)


class SyncResultResponse(ResponseModel):
    session_id: uuid.UUID
    outcome: str
    status: SessionStatus
    duration_seconds: int
    integrity_status: str
    reasons: list[str] = Field(default_factory=list)
    message: str | None = None


class SyncResponse(ResponseModel):
    results: list[SyncResultResponse]
