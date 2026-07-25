"""Channel authorization and event producers for the realtime layer.

Channels the client may ask for are virtual tokens (`friends`, `group:{id}`); the service
resolves and *authorizes* them into concrete channel names before the socket is subscribed,
so a user can only ever receive their own friend feed and the groups they may see.

Producers compute who should hear about an event and publish to those concrete channels.
Events are intentionally thin — a user id and a state — because the socket only accelerates
freshness (REALTIME.md): the client re-fetches the authoritative, privacy-filtered snapshot
over REST, so nothing here can leak what the snapshot would hide.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.errors import ErrorCode, NotFoundError
from app.domain.realtime.broadcaster import Broadcaster
from app.domain.realtime.hub import Message
from app.domain.social.service import PublicUserView, public_user_view
from app.models.enums import FriendshipStatus, GroupVisibility
from app.models.social import Encouragement, Friendship, GroupMembership, StudyGroup
from app.models.user import User

_ACCEPTED = FriendshipStatus.ACCEPTED.value

FRIENDS_TOKEN = "friends"
GROUP_PREFIX = "group:"


def friends_channel(user_id: uuid.UUID) -> str:
    return f"friends:{user_id}"


def group_channel(group_id: uuid.UUID) -> str:
    return f"group:{group_id}"


def resolve_channel_tokens(user_id: uuid.UUID, tokens: list[str]) -> list[str]:
    """Map tokens to concrete channels without authorization — for unsubscribe, which is safe."""
    resolved: list[str] = []
    for token in tokens:
        if token == FRIENDS_TOKEN:
            resolved.append(friends_channel(user_id))
        elif token.startswith(GROUP_PREFIX):
            group_id = _parse_uuid(token[len(GROUP_PREFIX) :])
            if group_id is not None:
                resolved.append(group_channel(group_id))
    return resolved


def presence_event(user: PublicUserView, state: str) -> Message:
    return {
        "event": "presence.changed",
        "data": {"user": _serialize(user), "state": state, "at": utc_now().isoformat()},
    }


def reaction_event(sender: PublicUserView, emoji: str) -> Message:
    return {
        "event": "reaction.created",
        "data": {"from": _serialize(sender), "emoji": emoji, "at": utc_now().isoformat()},
    }


def _serialize(user: PublicUserView) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "study_category": user.study_category,
    }


class RealtimeService:
    def __init__(self, db: AsyncSession, broadcaster: Broadcaster) -> None:
        self._db = db
        self._broadcaster = broadcaster

    # ------------------------------------------------------------------ authorization

    async def authorize_channels(self, user_id: uuid.UUID, tokens: list[str]) -> list[str]:
        """Resolve requested channel tokens to the concrete channels the user may receive."""
        allowed: list[str] = []
        for token in tokens:
            if token == FRIENDS_TOKEN:
                allowed.append(friends_channel(user_id))
            elif token.startswith(GROUP_PREFIX):
                group_id = _parse_uuid(token[len(GROUP_PREFIX) :])
                if group_id is not None and await self._can_see_group(user_id, group_id):
                    allowed.append(group_channel(group_id))
        return allowed

    async def _can_see_group(self, user_id: uuid.UUID, group_id: uuid.UUID) -> bool:
        group = await self._db.get(StudyGroup, group_id)
        if group is None or group.deleted_at is not None:
            return False
        if group.visibility == GroupVisibility.PUBLIC.value:
            return True
        return await self._is_member(group_id, user_id)

    # ------------------------------------------------------------------ producers

    async def publish_presence(self, user: User, state: str) -> None:
        """Notify the user's friends and groups that their live state changed."""
        event = presence_event(public_user_view(user, user.profile), state)
        for friend_id in await self._accepted_friend_ids(user.id):
            await self._broadcaster.publish(friends_channel(friend_id), event)
        for group_id in await self._member_group_ids(user.id):
            await self._broadcaster.publish(group_channel(group_id), event)

    async def publish_reaction(self, *, sender: User, target_id: uuid.UUID, emoji: str) -> None:
        """Send an encouragement to a friend's live feed. Only friends may react.

        Recorded as well as delivered: the league scores participation from these, and a
        season has to stay recomputable from stored facts.
        """
        if target_id not in await self._accepted_friend_ids(sender.id):
            raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found.")

        self._db.add(Encouragement(from_user_id=sender.id, to_user_id=target_id, emoji=emoji))
        await self._db.commit()

        event = reaction_event(public_user_view(sender, sender.profile), emoji)
        await self._broadcaster.publish(friends_channel(target_id), event)

    # ------------------------------------------------------------------ helpers

    async def _is_member(self, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self._db.execute(
            select(GroupMembership.id).where(
                GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
            )
        )
        return result.first() is not None

    async def _accepted_friend_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        result = await self._db.execute(
            select(Friendship).where(
                or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id),
                Friendship.status == _ACCEPTED,
            )
        )
        return {
            row.addressee_id if row.requester_id == user_id else row.requester_id
            for row in result.scalars().all()
        }

    async def _member_group_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        result = await self._db.execute(
            select(GroupMembership.group_id).where(GroupMembership.user_id == user_id)
        )
        return set(result.scalars().all())


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
