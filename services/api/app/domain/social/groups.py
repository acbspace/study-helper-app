"""Study groups: creation, membership, roles, invite codes, and invitations.

Roles form a strict rank — owner > moderator > member — and every management action is
gated on the actor out-ranking their target, so a moderator can remove members but never a
peer or the owner. Visibility decides who may even see a group: public groups are readable
by anyone, while invite/private groups are visible only to their members (a non-member gets
a plain "not found" so the group's existence stays hidden).

Groups are soft-deleted: the owner keeps a record for moderation, and every read filters
`deleted_at IS NULL` so a deleted group simply disappears.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.clock import ensure_utc, utc_now
from app.core.errors import AppError, ConflictError, ErrorCode, ForbiddenError, NotFoundError
from app.domain.social.service import PublicUserView
from app.models.enums import GroupRole, GroupVisibility, InvitationStatus
from app.models.social import GroupInvitation, GroupMembership, StudyGroup
from app.models.user import User, UserProfile

# Unambiguous alphabet (no 0/O or 1/I) so an invite code is easy to read out loud.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_INVITE_TTL_DAYS = 14

_ROLE_RANK = {GroupRole.OWNER.value: 2, GroupRole.MODERATOR.value: 1, GroupRole.MEMBER.value: 0}
_MANAGER_ROLES = (GroupRole.OWNER.value, GroupRole.MODERATOR.value)


@dataclass(frozen=True, slots=True)
class GroupMemberView:
    user: PublicUserView
    role: str
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class GroupSummaryView:
    id: uuid.UUID
    name: str
    description: str | None
    visibility: str
    member_count: int
    max_members: int
    owner: PublicUserView
    created_at: datetime
    # The caller's role in this group, or None when they are not a member.
    my_role: str | None


@dataclass(frozen=True, slots=True)
class GroupDetailView:
    group: GroupSummaryView
    rules: str | None
    members: list[GroupMemberView]
    # Only populated for members who can manage the group (owner / moderator).
    invite_code: str | None


@dataclass(frozen=True, slots=True)
class GroupInvitationView:
    id: uuid.UUID
    group: GroupSummaryView
    inviter: PublicUserView
    expires_at: datetime
    created_at: datetime


class GroupService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------ reads

    async def list_mine(self, user_id: uuid.UUID) -> list[GroupSummaryView]:
        result = await self._db.execute(
            select(GroupMembership, StudyGroup)
            .join(StudyGroup, StudyGroup.id == GroupMembership.group_id)
            .where(GroupMembership.user_id == user_id, StudyGroup.deleted_at.is_(None))
        )
        pairs = list(result.all())
        groups = [group for _, group in pairs]
        roles = {membership.group_id: membership.role for membership, _ in pairs}
        summaries = await self._summaries(groups, roles_by_group=roles)
        summaries.sort(key=lambda s: s.name.lower())
        return summaries

    async def discover(
        self, *, user_id: uuid.UUID, query: str, limit: int = 20
    ) -> list[GroupSummaryView]:
        needle = query.strip().lower()
        stmt = select(StudyGroup).where(
            StudyGroup.deleted_at.is_(None),
            StudyGroup.visibility == GroupVisibility.PUBLIC.value,
        )
        if needle:
            pattern = f"%{needle}%"
            stmt = stmt.where(
                or_(StudyGroup.name.ilike(pattern), StudyGroup.description.ilike(pattern))
            )
        result = await self._db.execute(stmt.order_by(StudyGroup.name).limit(limit))
        groups = list(result.scalars().all())
        roles = await self._roles_for(user_id, [g.id for g in groups])
        return await self._summaries(groups, roles_by_group=roles)

    async def get_detail(self, *, user_id: uuid.UUID, group_id: uuid.UUID) -> GroupDetailView:
        group = await self._require_group(group_id)
        membership = await self._membership(group_id, user_id)
        if group.visibility != GroupVisibility.PUBLIC.value and membership is None:
            # Hide the very existence of a group the caller may not see.
            raise NotFoundError(ErrorCode.GROUP_NOT_FOUND, "Group not found.")
        return await self._detail(group, membership)

    async def list_invitations(self, user_id: uuid.UUID) -> list[GroupInvitationView]:
        now = utc_now()
        result = await self._db.execute(
            select(GroupInvitation, StudyGroup)
            .join(StudyGroup, StudyGroup.id == GroupInvitation.group_id)
            .where(
                GroupInvitation.invitee_id == user_id,
                GroupInvitation.status == InvitationStatus.PENDING.value,
                GroupInvitation.expires_at > now,
                StudyGroup.deleted_at.is_(None),
            )
            .order_by(GroupInvitation.created_at.desc())
        )
        rows = list(result.all())
        summaries = {
            summary.id: summary
            for summary in await self._summaries([g for _, g in rows], roles_by_group={})
        }
        inviters = await self._load_public_users({inv.inviter_id for inv, _ in rows})
        views: list[GroupInvitationView] = []
        for invitation, group in rows:
            inviter = inviters.get(invitation.inviter_id)
            summary = summaries.get(group.id)
            if inviter is None or summary is None:
                continue
            views.append(
                GroupInvitationView(
                    id=invitation.id,
                    group=summary,
                    inviter=inviter,
                    expires_at=invitation.expires_at,
                    created_at=invitation.created_at,
                )
            )
        return views

    # ------------------------------------------------------------------ lifecycle

    async def create(
        self,
        *,
        owner: User,
        name: str,
        description: str | None = None,
        rules: str | None = None,
        visibility: str = GroupVisibility.PUBLIC.value,
        max_members: int = 50,
    ) -> GroupDetailView:
        now = utc_now()
        for _ in range(5):  # retry the (rare) invite-code collision
            group = StudyGroup(
                name=name.strip(),
                description=description,
                rules=rules,
                visibility=visibility,
                invite_code=self._generate_code(),
                max_members=max_members,
                owner_id=owner.id,
            )
            group.memberships.append(
                GroupMembership(user_id=owner.id, role=GroupRole.OWNER.value, joined_at=now)
            )
            self._db.add(group)
            try:
                await self._db.commit()
                break
            except IntegrityError:
                await self._db.rollback()
        else:  # pragma: no cover - astronomically unlikely
            raise AppError(ErrorCode.INTERNAL_ERROR, "Could not allocate an invite code.")

        await self._db.refresh(group)
        membership = await self._membership(group.id, owner.id)
        return await self._detail(group, membership)

    async def update(
        self,
        *,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        rules: str | None = None,
        visibility: str | None = None,
        max_members: int | None = None,
    ) -> GroupDetailView:
        group = await self._require_group(group_id)
        membership = await self._require_manager(group_id, user_id)

        if name is not None:
            group.name = name.strip()
        if description is not None:
            group.description = description
        if rules is not None:
            group.rules = rules
        if visibility is not None:
            group.visibility = visibility
        if max_members is not None:
            count = await self._member_count(group_id)
            if max_members < count:
                raise ConflictError(
                    ErrorCode.GROUP_FULL,
                    "The group already has more members than that new limit.",
                    member_count=count,
                )
            group.max_members = max_members

        await self._db.commit()
        await self._db.refresh(group)
        return await self._detail(group, membership)

    async def delete(self, *, user_id: uuid.UUID, group_id: uuid.UUID) -> None:
        group = await self._require_group(group_id)
        membership = await self._membership(group_id, user_id)
        if membership is None or membership.role != GroupRole.OWNER.value:
            raise ForbiddenError("Only the group owner can delete it.")
        group.deleted_at = utc_now()
        await self._db.commit()

    async def regenerate_invite_code(
        self, *, user_id: uuid.UUID, group_id: uuid.UUID
    ) -> GroupDetailView:
        group = await self._require_group(group_id)
        membership = await self._require_manager(group_id, user_id)
        for _ in range(5):
            group.invite_code = self._generate_code()
            try:
                await self._db.commit()
                break
            except IntegrityError:
                await self._db.rollback()
        else:  # pragma: no cover
            raise AppError(ErrorCode.INTERNAL_ERROR, "Could not allocate an invite code.")
        await self._db.refresh(group)
        return await self._detail(group, membership)

    # ------------------------------------------------------------------ membership

    async def join_public(self, *, user_id: uuid.UUID, group_id: uuid.UUID) -> GroupDetailView:
        group = await self._require_group(group_id)
        if group.visibility != GroupVisibility.PUBLIC.value:
            # Not a public group: don't confirm it exists to a non-member.
            raise NotFoundError(ErrorCode.GROUP_NOT_FOUND, "Group not found.")
        await self._add_member(group, user_id)
        await self._db.commit()
        return await self._detail(group, await self._membership(group.id, user_id))

    async def join_by_code(self, *, user_id: uuid.UUID, invite_code: str) -> GroupDetailView:
        result = await self._db.execute(
            select(StudyGroup).where(
                StudyGroup.invite_code == invite_code.strip().upper(),
                StudyGroup.deleted_at.is_(None),
            )
        )
        group = result.scalar_one_or_none()
        # A private group's code is not a public back door; it needs a personal invitation.
        if group is None or group.visibility == GroupVisibility.PRIVATE.value:
            raise NotFoundError(ErrorCode.INVALID_INVITE_CODE, "That invite code is not valid.")
        await self._add_member(group, user_id)
        await self._db.commit()
        return await self._detail(group, await self._membership(group.id, user_id))

    async def leave(self, *, user_id: uuid.UUID, group_id: uuid.UUID) -> None:
        group = await self._require_group(group_id)
        membership = await self._membership(group_id, user_id)
        if membership is None:
            raise NotFoundError(ErrorCode.NOT_GROUP_MEMBER, "You are not in this group.")

        if membership.role == GroupRole.OWNER.value:
            others = await self._member_count(group_id) - 1
            if others > 0:
                raise ConflictError(
                    ErrorCode.OWNER_CANNOT_LEAVE,
                    "Transfer the group or delete it before leaving.",
                )
            # The owner is the last member: leaving retires the group.
            group.deleted_at = utc_now()

        await self._db.delete(membership)
        await self._db.commit()

    async def remove_member(
        self, *, actor_id: uuid.UUID, group_id: uuid.UUID, target_id: uuid.UUID
    ) -> None:
        await self._require_group(group_id)
        actor = await self._require_manager(group_id, actor_id)
        if target_id == actor_id:
            raise ForbiddenError("Use leave to remove yourself.")
        target = await self._membership(group_id, target_id)
        if target is None:
            raise NotFoundError(ErrorCode.NOT_GROUP_MEMBER, "That user is not in this group.")
        if _ROLE_RANK[actor.role] <= _ROLE_RANK[target.role]:
            raise ForbiddenError("You cannot remove a member of equal or higher rank.")
        await self._db.delete(target)
        await self._db.commit()

    async def set_member_role(
        self, *, actor_id: uuid.UUID, group_id: uuid.UUID, target_id: uuid.UUID, role: str
    ) -> GroupMemberView:
        await self._require_group(group_id)
        actor = await self._membership(group_id, actor_id)
        if actor is None or actor.role != GroupRole.OWNER.value:
            raise ForbiddenError("Only the owner can change roles.")
        if role not in (GroupRole.MODERATOR.value, GroupRole.MEMBER.value):
            raise AppError(ErrorCode.VALIDATION_ERROR, "Role must be moderator or member.")
        target = await self._membership(group_id, target_id)
        if target is None or target.role == GroupRole.OWNER.value:
            raise NotFoundError(ErrorCode.NOT_GROUP_MEMBER, "That user is not a manageable member.")
        target.role = role
        await self._db.commit()
        users = await self._load_public_users({target_id})
        return GroupMemberView(user=users[target_id], role=target.role, joined_at=target.joined_at)

    # ------------------------------------------------------------------ invitations

    async def invite(
        self, *, actor_id: uuid.UUID, group_id: uuid.UUID, invitee_id: uuid.UUID
    ) -> GroupInvitationView:
        group = await self._require_group(group_id)
        await self._require_manager(group_id, actor_id)

        invitee = await self._require_active_user(invitee_id)
        if await self._membership(group_id, invitee.id) is not None:
            raise ConflictError(
                ErrorCode.ALREADY_GROUP_MEMBER, "That user is already in the group."
            )

        now = utc_now()
        expires_at = now + timedelta(days=_INVITE_TTL_DAYS)
        existing = await self._get_invitation_pair(group_id, invitee.id)
        if existing is not None:
            still_pending = (
                existing.status == InvitationStatus.PENDING.value
                and ensure_utc(existing.expires_at) > now
            )
            if still_pending:
                raise ConflictError(
                    ErrorCode.INVITATION_EXISTS, "That user already has a pending invitation."
                )
            # Re-open a stale/declined invitation rather than duplicating the pair.
            existing.status = InvitationStatus.PENDING.value
            existing.inviter_id = actor_id
            existing.expires_at = expires_at
            invitation = existing
        else:
            invitation = GroupInvitation(
                group_id=group_id,
                inviter_id=actor_id,
                invitee_id=invitee.id,
                status=InvitationStatus.PENDING.value,
                expires_at=expires_at,
            )
            self._db.add(invitation)
        await self._db.commit()
        await self._db.refresh(invitation)

        summary = (await self._summaries([group], roles_by_group={}))[0]
        inviter = (await self._load_public_users({actor_id}))[actor_id]
        return GroupInvitationView(
            id=invitation.id,
            group=summary,
            inviter=inviter,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )

    async def respond_invitation(
        self, *, user_id: uuid.UUID, invitation_id: uuid.UUID, accept: bool
    ) -> GroupDetailView | None:
        result = await self._db.execute(
            select(GroupInvitation).where(GroupInvitation.id == invitation_id)
        )
        invitation = result.scalar_one_or_none()
        now = utc_now()
        valid = (
            invitation is not None
            and invitation.invitee_id == user_id
            and invitation.status == InvitationStatus.PENDING.value
            and ensure_utc(invitation.expires_at) > now
        )
        if invitation is None or not valid:
            raise NotFoundError(ErrorCode.INVITATION_NOT_FOUND, "No pending invitation found.")

        if not accept:
            invitation.status = InvitationStatus.DECLINED.value
            await self._db.commit()
            return None

        group = await self._require_group(invitation.group_id)
        # Idempotent: accepting again just confirms membership.
        if await self._membership(group.id, user_id) is None:
            await self._add_member(group, user_id)
        invitation.status = InvitationStatus.ACCEPTED.value
        await self._db.commit()
        return await self._detail(group, await self._membership(group.id, user_id))

    # ------------------------------------------------------------------ helpers

    async def _require_group(self, group_id: uuid.UUID) -> StudyGroup:
        result = await self._db.execute(
            select(StudyGroup).where(StudyGroup.id == group_id, StudyGroup.deleted_at.is_(None))
        )
        group = result.scalar_one_or_none()
        if group is None:
            raise NotFoundError(ErrorCode.GROUP_NOT_FOUND, "Group not found.")
        return group

    async def _require_active_user(self, user_id: uuid.UUID) -> User:
        result = await self._db.execute(
            select(User).where(
                User.id == user_id, User.is_active.is_(True), User.deleted_at.is_(None)
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found.")
        return user

    async def _membership(self, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMembership | None:
        result = await self._db.execute(
            select(GroupMembership).where(
                GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def _require_manager(self, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMembership:
        membership = await self._membership(group_id, user_id)
        if membership is None:
            raise NotFoundError(ErrorCode.NOT_GROUP_MEMBER, "You are not in this group.")
        if membership.role not in _MANAGER_ROLES:
            raise ForbiddenError("Only owners and moderators can do that.")
        return membership

    async def _member_count(self, group_id: uuid.UUID) -> int:
        result = await self._db.execute(
            select(func.count())
            .select_from(GroupMembership)
            .where(GroupMembership.group_id == group_id)
        )
        return int(result.scalar_one())

    async def _add_member(
        self, group: StudyGroup, user_id: uuid.UUID, *, role: str = GroupRole.MEMBER.value
    ) -> None:
        """Validate and stage a new membership; the caller commits."""
        if await self._membership(group.id, user_id) is not None:
            raise ConflictError(ErrorCode.ALREADY_GROUP_MEMBER, "You are already in this group.")
        if await self._member_count(group.id) >= group.max_members:
            raise ConflictError(ErrorCode.GROUP_FULL, "This group is full.")
        self._db.add(
            GroupMembership(group_id=group.id, user_id=user_id, role=role, joined_at=utc_now())
        )

    async def _get_invitation_pair(
        self, group_id: uuid.UUID, invitee_id: uuid.UUID
    ) -> GroupInvitation | None:
        result = await self._db.execute(
            select(GroupInvitation).where(
                GroupInvitation.group_id == group_id,
                GroupInvitation.invitee_id == invitee_id,
            )
        )
        return result.scalar_one_or_none()

    async def _roles_for(
        self, user_id: uuid.UUID, group_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        if not group_ids:
            return {}
        result = await self._db.execute(
            select(GroupMembership.group_id, GroupMembership.role).where(
                GroupMembership.user_id == user_id,
                GroupMembership.group_id.in_(group_ids),
            )
        )
        return {row.group_id: row.role for row in result.all()}

    async def _counts_for(self, group_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not group_ids:
            return {}
        result = await self._db.execute(
            select(GroupMembership.group_id, func.count())
            .where(GroupMembership.group_id.in_(group_ids))
            .group_by(GroupMembership.group_id)
        )
        return {group_id: int(count) for group_id, count in result.all()}

    async def _summaries(
        self,
        groups: list[StudyGroup],
        *,
        roles_by_group: dict[uuid.UUID, str],
    ) -> list[GroupSummaryView]:
        if not groups:
            return []
        group_ids = [g.id for g in groups]
        counts = await self._counts_for(group_ids)
        owners = await self._load_public_users({g.owner_id for g in groups})
        summaries: list[GroupSummaryView] = []
        for group in groups:
            owner = owners.get(group.owner_id)
            if owner is None:
                continue
            summaries.append(
                GroupSummaryView(
                    id=group.id,
                    name=group.name,
                    description=group.description,
                    visibility=group.visibility,
                    member_count=counts.get(group.id, 0),
                    max_members=group.max_members,
                    owner=owner,
                    created_at=group.created_at,
                    my_role=roles_by_group.get(group.id),
                )
            )
        return summaries

    async def _detail(
        self, group: StudyGroup, membership: GroupMembership | None
    ) -> GroupDetailView:
        result = await self._db.execute(
            select(GroupMembership, User, UserProfile)
            .join(User, User.id == GroupMembership.user_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(GroupMembership.group_id == group.id)
        )
        members = [
            GroupMemberView(
                user=_public_view(user, profile),
                role=membership_row.role,
                joined_at=membership_row.joined_at,
            )
            for membership_row, user, profile in result.all()
        ]
        members.sort(key=lambda m: (-_ROLE_RANK.get(m.role, 0), m.joined_at))

        my_role = membership.role if membership is not None else None
        summary = GroupSummaryView(
            id=group.id,
            name=group.name,
            description=group.description,
            visibility=group.visibility,
            member_count=len(members),
            max_members=group.max_members,
            owner=_owner_view(members, group.owner_id),
            created_at=group.created_at,
            my_role=my_role,
        )
        can_manage = my_role in _MANAGER_ROLES
        return GroupDetailView(
            group=summary,
            rules=group.rules,
            members=members,
            invite_code=group.invite_code if can_manage else None,
        )

    async def _load_public_users(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, PublicUserView]:
        if not ids:
            return {}
        result = await self._db.execute(
            select(User)
            .options(selectinload(User.profile))
            .where(User.id.in_(ids), User.deleted_at.is_(None))
        )
        return {user.id: _public_view(user, user.profile) for user in result.scalars().all()}

    def _generate_code(self) -> str:
        return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _public_view(user: User, profile: UserProfile) -> PublicUserView:
    return PublicUserView(
        id=user.id,
        username=profile.username,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        country_code=profile.country_code,
        study_category=profile.study_category,
    )


def _owner_view(members: list[GroupMemberView], owner_id: uuid.UUID) -> PublicUserView:
    for member in members:
        if member.user.id == owner_id and member.role == GroupRole.OWNER.value:
            return member.user
    # The owner is always a member, but fall back to the first member to stay total.
    return members[0].user
