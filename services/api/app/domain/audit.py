"""Append-only audit trail.

There is deliberately no update or delete helper here: the table's value comes from its
entries being immutable. Every score-affecting change writes one row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import ensure_utc
from app.models.enums import ActorType
from app.models.platform import AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    actor_type: ActorType,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    now: datetime,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    """Append one audit entry. The caller owns the surrounding transaction."""
    entry = AuditLog(
        actor_type=actor_type.value,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        reason=reason,
        created_at=ensure_utc(now),
    )
    db.add(entry)
    return entry
