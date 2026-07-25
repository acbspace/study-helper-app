"""Subjects, study sessions, the session event log, and long-horizon goals."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JsonDocument, UtcDateTime, UuidType
from app.models.enums import FocusMode, IntegrityStatus, SessionSource, SessionStatus

if TYPE_CHECKING:
    from app.models.user import User


class Subject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subjects"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    color_hex: Mapped[str] = mapped_column(String(7), nullable=False, default="#4F6BED")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship(back_populates="subjects")

    __table_args__ = (
        # Active subject names are unique per user; archived names may repeat.
        Index(
            "uq_subjects_user_name_active",
            "user_id",
            text("lower(name)"),
            unique=True,
            sqlite_where=text("is_archived = 0"),
            postgresql_where=text("is_archived = false"),
        ),
        CheckConstraint("length(color_hex) = 7", name="ck_subjects_color_format"),
    )


class StudySession(Base, TimestampMixin):
    """A study session.

    The id is client-generated so a device can create sessions offline and sync them
    idempotently. `duration_seconds` is a materialised cache of the event timeline — it is
    always recomputable from `events` (see app/domain/sessions/timeline.py).
    """

    __tablename__ = "study_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(
        String(8), nullable=False, default=SessionSource.TIMER.value
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=SessionStatus.ACTIVE.value
    )
    focus_mode: Mapped[str] = mapped_column(
        String(12), nullable=False, default=FocusMode.STOPWATCH.value
    )
    pomodoro_focus_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    went_as_planned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    integrity_status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=IntegrityStatus.OK.value
    )
    integrity_reasons: Mapped[list[str]] = mapped_column(JsonDocument, nullable=False, default=list)

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    client_created_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    events: Mapped[list[StudySessionEvent]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="StudySessionEvent.sequence",
    )
    subject: Mapped[Subject] = relationship()

    __table_args__ = (
        # Invariant #1: at most one running session per user, enforced by the database
        # rather than by application checks alone.
        Index(
            "uq_one_running_session_per_user",
            "user_id",
            unique=True,
            sqlite_where=text("status IN ('active', 'paused')"),
            postgresql_where=text("status IN ('active', 'paused')"),
        ),
        Index("ix_sessions_user_started", "user_id", "started_at"),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ck_sessions_ended_after_started"
        ),
        CheckConstraint("duration_seconds >= 0", name="ck_sessions_duration_non_negative"),
        CheckConstraint(
            "source <> 'manual' OR (status = 'completed' AND ended_at IS NOT NULL)",
            name="ck_manual_sessions_are_complete",
        ),
    )


class StudySessionEvent(Base, TimestampMixin):
    """Append-only timer transition.

    `(session_id, sequence)` uniqueness is the idempotency backbone for offline sync: a
    replayed batch re-inserts nothing. Rows are never updated or deleted.
    """

    __tablename__ = "study_session_events"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(8), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False, default=dict)

    session: Mapped[StudySession] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_session_event_sequence"),
        CheckConstraint("sequence >= 1", name="ck_event_sequence_positive"),
    )


class StudyGoal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A D-Day style goal: a target date plus a weekly time commitment."""

    __tablename__ = "study_goals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_weekly_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subject_ids: Mapped[list[str]] = mapped_column(JsonDocument, nullable=False, default=list)
    milestones: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonDocument, nullable=False, default=list
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("target_weekly_minutes >= 0", name="ck_goal_weekly_minutes_non_negative"),
    )
