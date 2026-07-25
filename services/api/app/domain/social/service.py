"""Friendships: requests, acceptance, removal, blocking, and user search.

A friendship is stored as a single directional row (`requester` → `addressee`) but is
semantically *undirected* once accepted: A and B are friends regardless of who asked. Every
lookup therefore checks both directions. The unique constraint is on the ordered pair, so at
most one row exists per direction and blocking is normalised so the blocker is always the
`requester` of the blocked row — that way `requester` unambiguously means "the blocker".

What the service refuses to leak: whether another user has blocked you. A request to someone
who blocked you fails as `user_not_found`, and users who blocked you never appear in search,
so a block is invisible from the outside rather than an announcement.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.clock import utc_now
from app.core.errors import AppError, ConflictError, ErrorCode, NotFoundError
from app.models.enums import FriendshipStatus
from app.models.social import Friendship
from app.models.user import User, UserProfile


class RelationshipState(StrEnum):
    """The caller's relationship to another user, computed for search results."""

    NONE = "none"
    FRIENDS = "friends"
    REQUEST_SENT = "request_sent"
    REQUEST_RECEIVED = "request_received"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PublicUserView:
    """The slice of another user that is safe to show — never their email."""

    id: uuid.UUID
    username: str
    display_name: str
    avatar_url: str | None
    country_code: str | None
    study_category: str


@dataclass(frozen=True, slots=True)
class FriendView:
    friendship_id: uuid.UUID
    user: PublicUserView
    since: datetime | None


@dataclass(frozen=True, slots=True)
class RequestView:
    friendship_id: uuid.UUID
    direction: str  # "incoming" (they asked you) or "outgoing" (you asked them)
    status: str  # "pending", or "accepted" when sending a request auto-accepts a mirror one
    user: PublicUserView
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RequestsView:
    incoming: list[RequestView]
    outgoing: list[RequestView]


@dataclass(frozen=True, slots=True)
class SearchResultView:
    user: PublicUserView
    relationship: RelationshipState
    friendship_id: uuid.UUID | None


_PENDING = FriendshipStatus.PENDING.value
_ACCEPTED = FriendshipStatus.ACCEPTED.value
_DECLINED = FriendshipStatus.DECLINED.value
_BLOCKED = FriendshipStatus.BLOCKED.value


class FriendshipService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------ reads

    async def list_friends(self, user_id: uuid.UUID) -> list[FriendView]:
        rows = await self._friendships_of(user_id, status=_ACCEPTED)
        others = await self._load_public({self._other_id(user_id, row) for row in rows})
        views = [
            FriendView(
                friendship_id=row.id,
                user=others[self._other_id(user_id, row)],
                since=row.responded_at,
            )
            for row in rows
            if self._other_id(user_id, row) in others
        ]
        views.sort(key=lambda v: v.user.display_name.lower())
        return views

    async def list_requests(self, user_id: uuid.UUID) -> RequestsView:
        rows = await self._friendships_of(user_id, status=_PENDING)
        others = await self._load_public({self._other_id(user_id, row) for row in rows})
        incoming: list[RequestView] = []
        outgoing: list[RequestView] = []
        for row in rows:
            other = others.get(self._other_id(user_id, row))
            if other is None:
                continue
            if row.addressee_id == user_id:
                incoming.append(RequestView(row.id, "incoming", row.status, other, row.created_at))
            else:
                outgoing.append(RequestView(row.id, "outgoing", row.status, other, row.created_at))
        incoming.sort(key=lambda v: v.created_at, reverse=True)
        outgoing.sort(key=lambda v: v.created_at, reverse=True)
        return RequestsView(incoming=incoming, outgoing=outgoing)

    async def list_blocked(self, user_id: uuid.UUID) -> list[PublicUserView]:
        result = await self._db.execute(
            select(Friendship).where(
                Friendship.requester_id == user_id, Friendship.status == _BLOCKED
            )
        )
        rows = list(result.scalars().all())
        others = await self._load_public({row.addressee_id for row in rows})
        views = [others[row.addressee_id] for row in rows if row.addressee_id in others]
        views.sort(key=lambda v: v.display_name.lower())
        return views

    async def search(
        self, *, user_id: uuid.UUID, query: str, limit: int = 20
    ) -> list[SearchResultView]:
        needle = query.strip().lower()
        if not needle:
            return []

        pattern = f"%{needle}%"
        result = await self._db.execute(
            select(UserProfile, User)
            .join(User, User.id == UserProfile.user_id)
            .where(
                User.id != user_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                or_(
                    UserProfile.username.ilike(pattern),
                    UserProfile.display_name.ilike(pattern),
                ),
            )
            .order_by(UserProfile.username)
            .limit(limit * 2)  # over-fetch: some are dropped for blocking the caller
        )
        candidates = [(profile, u) for profile, u in result.all()]

        edges = await self._edges_by_other(user_id)
        results: list[SearchResultView] = []
        for profile, candidate in candidates:
            forward, reverse = edges.get(candidate.id, (None, None))
            # Someone who blocked us stays invisible.
            if reverse is not None and reverse.status == _BLOCKED:
                continue
            state, friendship_id = self._classify(forward, reverse)
            results.append(
                SearchResultView(
                    user=self._view(candidate, profile),
                    relationship=state,
                    friendship_id=friendship_id,
                )
            )
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------------------ writes

    async def send_request(
        self,
        *,
        requester: User,
        addressee_id: uuid.UUID | None = None,
        username: str | None = None,
    ) -> RequestView:
        target = await self._resolve_target(addressee_id=addressee_id, username=username)
        if target.id == requester.id:
            raise AppError(
                ErrorCode.CANNOT_FRIEND_SELF, "You cannot send yourself a friend request."
            )

        # If they blocked us, behave exactly as if they did not exist.
        if await self._has_blocked(blocker_id=target.id, target_id=requester.id):
            raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found.")

        forward = await self._get_exact(requester.id, target.id)
        reverse = await self._get_exact(target.id, requester.id)

        if forward is not None and forward.status == _BLOCKED:
            raise ConflictError(
                ErrorCode.USER_BLOCKED,
                "You have blocked this user. Unblock them before sending a request.",
            )
        if self._are_friends(forward, reverse):
            raise ConflictError(ErrorCode.ALREADY_FRIENDS, "You are already friends.")

        # They already asked us: accept instead of stacking a mirror-image request.
        if reverse is not None and reverse.status == _PENDING:
            reverse.status = _ACCEPTED
            reverse.responded_at = utc_now()
            await self._db.commit()
            return await self._request_view(reverse, viewer_id=requester.id)

        if forward is not None and forward.status == _PENDING:
            raise ConflictError(
                ErrorCode.FRIEND_REQUEST_EXISTS, "You already have a pending request to this user."
            )

        if forward is not None and forward.status == _DECLINED:
            # Re-open our previously declined request rather than duplicating the pair.
            forward.status = _PENDING
            forward.responded_at = None
            await self._db.commit()
            return await self._request_view(forward, viewer_id=requester.id)

        if reverse is not None and reverse.status == _DECLINED:
            # We once declined them; clear the stale row so the pair is clean.
            await self._db.delete(reverse)

        friendship = Friendship(requester_id=requester.id, addressee_id=target.id, status=_PENDING)
        self._db.add(friendship)
        await self._db.commit()
        await self._db.refresh(friendship)
        return await self._request_view(friendship, viewer_id=requester.id)

    async def accept(self, *, user_id: uuid.UUID, friendship_id: uuid.UUID) -> FriendView:
        friendship = await self._pending_addressed_to(user_id, friendship_id)
        friendship.status = _ACCEPTED
        friendship.responded_at = utc_now()
        await self._db.commit()
        other = await self._load_public({friendship.requester_id})
        return FriendView(
            friendship_id=friendship.id,
            user=other[friendship.requester_id],
            since=friendship.responded_at,
        )

    async def decline(self, *, user_id: uuid.UUID, friendship_id: uuid.UUID) -> None:
        friendship = await self._pending_addressed_to(user_id, friendship_id)
        friendship.status = _DECLINED
        friendship.responded_at = utc_now()
        await self._db.commit()

    async def remove(self, *, user_id: uuid.UUID, friendship_id: uuid.UUID) -> None:
        """Cancel an outgoing request or unfriend — either party, but not a block."""
        friendship = await self._get_by_id(friendship_id)
        involved = friendship is not None and user_id in (
            friendship.requester_id,
            friendship.addressee_id,
        )
        if friendship is None or not involved or friendship.status == _BLOCKED:
            raise NotFoundError(ErrorCode.FRIENDSHIP_NOT_FOUND, "No such friendship or request.")
        await self._db.delete(friendship)
        await self._db.commit()

    async def block(self, *, user_id: uuid.UUID, target_id: uuid.UUID) -> None:
        if user_id == target_id:
            raise AppError(ErrorCode.CANNOT_FRIEND_SELF, "You cannot block yourself.")
        await self._resolve_target(addressee_id=target_id)

        now = utc_now()
        # A row where the target is the requester can't be repurposed as *our* block
        # (requester must be the blocker), so drop it unless it is the target blocking us.
        reverse = await self._get_exact(target_id, user_id)
        if reverse is not None and reverse.status != _BLOCKED:
            await self._db.delete(reverse)

        forward = await self._get_exact(user_id, target_id)
        if forward is not None:
            forward.status = _BLOCKED
            forward.responded_at = now
        else:
            self._db.add(
                Friendship(
                    requester_id=user_id,
                    addressee_id=target_id,
                    status=_BLOCKED,
                    responded_at=now,
                )
            )
        await self._db.commit()

    async def unblock(self, *, user_id: uuid.UUID, target_id: uuid.UUID) -> None:
        forward = await self._get_exact(user_id, target_id)
        if forward is None or forward.status != _BLOCKED:
            raise NotFoundError(ErrorCode.FRIENDSHIP_NOT_FOUND, "You have not blocked this user.")
        await self._db.delete(forward)
        await self._db.commit()

    # ------------------------------------------------------------------ helpers

    async def _resolve_target(
        self, *, addressee_id: uuid.UUID | None = None, username: str | None = None
    ) -> User:
        if addressee_id is not None:
            stmt = select(User).where(User.id == addressee_id)
        elif username is not None:
            stmt = (
                select(User)
                .join(UserProfile, UserProfile.user_id == User.id)
                .where(func.lower(UserProfile.username) == username.strip().lower())
            )
        else:
            raise AppError(ErrorCode.VALIDATION_ERROR, "A user id or username is required.")

        result = await self._db.execute(
            stmt.where(User.is_active.is_(True), User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found.")
        return user

    async def _get_by_id(self, friendship_id: uuid.UUID) -> Friendship | None:
        result = await self._db.execute(select(Friendship).where(Friendship.id == friendship_id))
        return result.scalar_one_or_none()

    async def _get_exact(
        self, requester_id: uuid.UUID, addressee_id: uuid.UUID
    ) -> Friendship | None:
        result = await self._db.execute(
            select(Friendship).where(
                Friendship.requester_id == requester_id,
                Friendship.addressee_id == addressee_id,
            )
        )
        return result.scalar_one_or_none()

    async def _pending_addressed_to(
        self, user_id: uuid.UUID, friendship_id: uuid.UUID
    ) -> Friendship:
        friendship = await self._get_by_id(friendship_id)
        # Only the addressee can respond, and only while it is pending. Anything else is
        # reported as "not found" so a request's existence can't be probed by outsiders.
        if (
            friendship is None
            or friendship.addressee_id != user_id
            or friendship.status != _PENDING
        ):
            raise NotFoundError(ErrorCode.FRIENDSHIP_NOT_FOUND, "No pending request found.")
        return friendship

    async def _has_blocked(self, *, blocker_id: uuid.UUID, target_id: uuid.UUID) -> bool:
        row = await self._get_exact(blocker_id, target_id)
        return row is not None and row.status == _BLOCKED

    async def _friendships_of(self, user_id: uuid.UUID, *, status: str) -> list[Friendship]:
        result = await self._db.execute(
            select(Friendship).where(
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id,
                ),
                Friendship.status == status,
            )
        )
        return list(result.scalars().all())

    async def _edges_by_other(
        self, user_id: uuid.UUID
    ) -> dict[uuid.UUID, tuple[Friendship | None, Friendship | None]]:
        """Every friendship row touching the user, keyed by the other user.

        Each value is `(forward, reverse)`: the row where the user is the requester and the
        row where the user is the addressee, so a relationship can be classified without
        another round trip per candidate.
        """
        result = await self._db.execute(
            select(Friendship).where(
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id,
                )
            )
        )
        edges: dict[uuid.UUID, tuple[Friendship | None, Friendship | None]] = {}
        for row in result.scalars().all():
            other_id = self._other_id(user_id, row)
            forward, reverse = edges.get(other_id, (None, None))
            if row.requester_id == user_id:
                forward = row
            else:
                reverse = row
            edges[other_id] = (forward, reverse)
        return edges

    async def _load_public(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, PublicUserView]:
        return await load_public_users(self._db, ids)

    @staticmethod
    def _other_id(user_id: uuid.UUID, row: Friendship) -> uuid.UUID:
        return row.addressee_id if row.requester_id == user_id else row.requester_id

    @staticmethod
    def _are_friends(forward: Friendship | None, reverse: Friendship | None) -> bool:
        return (forward is not None and forward.status == _ACCEPTED) or (
            reverse is not None and reverse.status == _ACCEPTED
        )

    @staticmethod
    def _classify(
        forward: Friendship | None, reverse: Friendship | None
    ) -> tuple[RelationshipState, uuid.UUID | None]:
        if forward is not None and forward.status == _BLOCKED:
            return RelationshipState.BLOCKED, forward.id
        if FriendshipService._are_friends(forward, reverse):
            row = forward if (forward and forward.status == _ACCEPTED) else reverse
            return RelationshipState.FRIENDS, row.id if row else None
        if forward is not None and forward.status == _PENDING:
            return RelationshipState.REQUEST_SENT, forward.id
        if reverse is not None and reverse.status == _PENDING:
            return RelationshipState.REQUEST_RECEIVED, reverse.id
        return RelationshipState.NONE, None

    @staticmethod
    def _view(user: User, profile: UserProfile) -> PublicUserView:
        return public_user_view(user, profile)

    async def _request_view(self, friendship: Friendship, *, viewer_id: uuid.UUID) -> RequestView:
        other_id = self._other_id(viewer_id, friendship)
        others = await self._load_public({other_id})
        direction = "outgoing" if friendship.requester_id == viewer_id else "incoming"
        return RequestView(
            friendship_id=friendship.id,
            direction=direction,
            status=friendship.status,
            user=others[other_id],
            created_at=friendship.created_at,
        )


def public_user_view(user: User, profile: UserProfile) -> PublicUserView:
    """The shared, email-free projection of a user for any social surface."""
    return PublicUserView(
        id=user.id,
        username=profile.username,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        country_code=profile.country_code,
        study_category=profile.study_category,
    )


async def load_public_users(
    db: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, PublicUserView]:
    """Batch-load public views for a set of user ids, skipping deleted accounts."""
    if not ids:
        return {}
    result = await db.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.id.in_(ids), User.deleted_at.is_(None))
    )
    return {user.id: public_user_view(user, user.profile) for user in result.scalars().all()}
