"""Live presence: who is studying right now.

Presence is deliberately ephemeral (ADR-0005): a short-lived document per user with a TTL,
refreshed by a client heartbeat, so a device that dies silently simply expires to "offline"
with nothing to clean up. Nothing here is durable — losing the whole store loses only
liveness, never study history.

Privacy is applied **at write time**: a user who hides presence stores nothing at all, and a
user who hides their subject stores no subject. Consumers therefore cannot leak what was
never written. Reads additionally drop anyone on either side of a block.

Two backends implement the same tiny interface: Redis in production (shared across API
instances, native TTL) and an in-process store for single-instance dev and tests. The
service is identical against either.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.errors import ErrorCode, NotFoundError
from app.core.logging import get_logger
from app.domain.social.service import PublicUserView, load_public_users
from app.models.enums import FriendshipStatus, GroupVisibility
from app.models.social import Friendship, GroupMembership, StudyGroup
from app.models.user import User

logger = get_logger(__name__)

PRESENCE_TTL_SECONDS = 90
_KEY_PREFIX = "presence:"

# Ordering for snapshots: active studiers first, then breaks, then idle.
_STATE_ORDER = {"studying": 0, "break": 1, "idle": 2}


class PresenceState(StrEnum):
    STUDYING = "studying"
    BREAK = "break"
    IDLE = "idle"


@dataclass(frozen=True, slots=True)
class UserPresenceView:
    user: PublicUserView
    state: str
    subject_id: uuid.UUID | None
    started_at: datetime | None
    updated_at: datetime


# ---------------------------------------------------------------------------- stores


class PresenceStore:
    """The minimal contract the service needs: put-with-TTL, batch get, clear."""

    async def put(self, user_id: uuid.UUID, doc: dict[str, object]) -> None:
        raise NotImplementedError

    async def get_many(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, object]]:
        raise NotImplementedError

    async def clear(self, user_id: uuid.UUID) -> None:
        raise NotImplementedError


class InMemoryPresenceStore(PresenceStore):
    """Single-process store with wall-clock TTL. Used for dev without Redis and for tests."""

    def __init__(self, ttl_seconds: int = PRESENCE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[uuid.UUID, tuple[dict[str, object], float]] = {}

    async def put(self, user_id: uuid.UUID, doc: dict[str, object]) -> None:
        self._entries[user_id] = (doc, time.time() + self._ttl)

    async def get_many(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, object]]:
        now = time.time()
        result: dict[uuid.UUID, dict[str, object]] = {}
        for user_id in user_ids:
            entry = self._entries.get(user_id)
            if entry is None:
                continue
            doc, expires_at = entry
            if expires_at <= now:
                self._entries.pop(user_id, None)  # lazily evict the expired doc
                continue
            result[user_id] = doc
        return result

    async def clear(self, user_id: uuid.UUID) -> None:
        self._entries.pop(user_id, None)


class RedisPresenceStore(PresenceStore):
    """Shared, TTL'd presence across API instances. Fails soft: a Redis error reads empty."""

    def __init__(self, redis: object, ttl_seconds: int = PRESENCE_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def put(self, user_id: uuid.UUID, doc: dict[str, object]) -> None:
        try:
            await self._redis.set(_KEY_PREFIX + str(user_id), json.dumps(doc), ex=self._ttl)  # type: ignore[attr-defined]
        except Exception as exc:  # presence must never break a request
            logger.warning("presence_write_failed", error=str(exc))

    async def get_many(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, object]]:
        if not user_ids:
            return {}
        ordered: list[uuid.UUID] = list(user_ids)
        keys = [_KEY_PREFIX + str(uid) for uid in ordered]
        try:
            raw = await self._redis.mget(keys)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("presence_read_failed", error=str(exc))
            return {}
        result: dict[uuid.UUID, dict[str, object]] = {}
        for user_id, value in zip(ordered, raw, strict=True):
            if value is None:
                continue
            try:
                result[user_id] = json.loads(value)
            except (ValueError, TypeError):
                continue
        return result

    async def clear(self, user_id: uuid.UUID) -> None:
        try:
            await self._redis.delete(_KEY_PREFIX + str(user_id))  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("presence_clear_failed", error=str(exc))


def build_presence_store(redis: object | None) -> PresenceStore:
    """Redis when it is available, otherwise the in-process fallback."""
    return RedisPresenceStore(redis) if redis is not None else InMemoryPresenceStore()


# ---------------------------------------------------------------------------- service


_ACCEPTED = FriendshipStatus.ACCEPTED.value
_BLOCKED = FriendshipStatus.BLOCKED.value


class PresenceService:
    def __init__(self, db: AsyncSession, store: PresenceStore) -> None:
        self._db = db
        self._store = store

    async def heartbeat(
        self,
        *,
        user: User,
        state: PresenceState,
        subject_id: uuid.UUID | None,
        started_at: datetime | None,
    ) -> None:
        # A user who hides presence broadcasts nothing — and any stale doc is cleared.
        if not user.settings.privacy_show_presence:
            await self._store.clear(user.id)
            return

        show_subject = user.settings.privacy_show_subject and state is PresenceState.STUDYING
        doc: dict[str, object] = {
            "state": state.value,
            "subject_id": str(subject_id) if (subject_id and show_subject) else None,
            "started_at": started_at.isoformat() if started_at else None,
            "updated_at": utc_now().isoformat(),
        }
        await self._store.put(user.id, doc)

    async def clear(self, user_id: uuid.UUID) -> None:
        await self._store.clear(user_id)

    async def friends_presence(self, user: User) -> list[UserPresenceView]:
        friend_ids = await self._accepted_friend_ids(user.id)
        return await self._snapshot(user, friend_ids)

    async def group_presence(self, user: User, group_id: uuid.UUID) -> list[UserPresenceView]:
        group = await self._db.get(StudyGroup, group_id)
        if group is None or group.deleted_at is not None:
            raise NotFoundError(ErrorCode.GROUP_NOT_FOUND, "Group not found.")

        member_ids = await self._group_member_ids(group_id)
        if group.visibility != GroupVisibility.PUBLIC.value and user.id not in member_ids:
            raise NotFoundError(ErrorCode.GROUP_NOT_FOUND, "Group not found.")

        return await self._snapshot(user, member_ids - {user.id})

    # ------------------------------------------------------------------ helpers

    async def _snapshot(self, user: User, candidate_ids: set[uuid.UUID]) -> list[UserPresenceView]:
        if not candidate_ids:
            return []
        blocked = await self._blocked_relative_to(user.id)
        visible = candidate_ids - blocked
        docs = await self._store.get_many(visible)
        if not docs:
            return []

        users = await load_public_users(self._db, set(docs))
        views: list[UserPresenceView] = []
        for user_id, doc in docs.items():
            profile = users.get(user_id)
            if profile is None:
                continue
            views.append(_to_view(profile, doc))
        views.sort(key=lambda v: (_STATE_ORDER.get(v.state, 9), v.user.display_name.lower()))
        return views

    async def _accepted_friend_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        result = await self._db.execute(
            select(Friendship).where(
                or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
                Friendship.status == _ACCEPTED,
            )
        )
        ids: set[uuid.UUID] = set()
        for row in result.scalars().all():
            ids.add(row.addressee_id if row.requester_id == user_id else row.requester_id)
        return ids

    async def _blocked_relative_to(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        """Everyone on either side of a block with this user — hidden from each other."""
        result = await self._db.execute(
            select(Friendship).where(
                or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
                Friendship.status == _BLOCKED,
            )
        )
        ids: set[uuid.UUID] = set()
        for row in result.scalars().all():
            ids.add(row.addressee_id if row.requester_id == user_id else row.requester_id)
        return ids

    async def _group_member_ids(self, group_id: uuid.UUID) -> set[uuid.UUID]:
        result = await self._db.execute(
            select(GroupMembership.user_id).where(GroupMembership.group_id == group_id)
        )
        return set(result.scalars().all())


def _to_view(profile: PublicUserView, doc: dict[str, object]) -> UserPresenceView:
    return UserPresenceView(
        user=profile,
        state=str(doc.get("state", PresenceState.IDLE.value)),
        subject_id=_maybe_uuid(doc.get("subject_id")),
        started_at=_maybe_dt(doc.get("started_at")),
        updated_at=_maybe_dt(doc.get("updated_at")) or utc_now(),
    )


def _maybe_uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _maybe_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
