"""Notifications, moderation reports, and the append-only audit log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JsonDocument, UtcDateTime, UuidType
from app.models.enums import ReportStatus


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # When push delivery was attempted. NULL means the delivery worker has not seen it yet;
    # it is the idempotency marker that stops a notification being pushed twice.
    pushed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)


class Report(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reports"

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=ReportStatus.OPEN.value)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_reports_subject", "subject_type", "subject_id"),)


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """Append-only record of score-affecting and moderation changes.

    Intentionally has no `updated_at` and no update/delete path anywhere in the codebase:
    the value of this table is that entries cannot be rewritten.
    """

    __tablename__ = "audit_logs"

    actor_type: Mapped[str] = mapped_column(String(8), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_created", "created_at"),
    )


class IdempotencyRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Stored responses for retry-sensitive writes (see API_CONVENTIONS.md)."""

    __tablename__ = "idempotency_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JsonDocument, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("uq_idempotency_user_key_endpoint", "user_id", "key", "endpoint", unique=True),
    )
