"""Friendships, study groups, memberships, and invitations.

Schema lands in M1 so migrations stay linear; endpoints arrive in M2 (see ROADMAP.md).
Presence is deliberately absent — it lives in Redis with a TTL (ADR-0005).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UtcDateTime, UuidType
from app.models.enums import (
    FriendshipStatus,
    GroupRole,
    GroupVisibility,
    InvitationStatus,
)


class Friendship(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "friendships"

    requester_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addressee_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=FriendshipStatus.PENDING.value
    )
    responded_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
        CheckConstraint("requester_id <> addressee_id", name="ck_friendship_not_self"),
    )


class StudyGroup(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "study_groups"

    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(8), nullable=False, default=GroupVisibility.PUBLIC.value
    )
    invite_code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    max_members: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # Soft delete: moderation history must survive group deletion.
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )

    __table_args__ = (CheckConstraint("max_members BETWEEN 2 AND 500", name="ck_group_capacity"),)


class GroupMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "group_memberships"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False, default=GroupRole.MEMBER.value)
    joined_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    group: Mapped[StudyGroup] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_membership"),
        Index("ix_group_memberships_user", "user_id"),
    )


class Encouragement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A reaction sent to a friend.

    Delivered live over the socket, but persisted because it is the fact behind the league's
    "positive group participation" component — a score has to be recomputable from stored
    inputs (ADR-0006), so the thing being scored cannot be ephemeral.
    """

    __tablename__ = "encouragements"

    from_user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        CheckConstraint("from_user_id <> to_user_id", name="ck_encouragement_not_self"),
        Index("ix_encouragements_from_created", "from_user_id", "created_at"),
    )


class GroupInvitation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "group_invitations"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    invitee_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=InvitationStatus.PENDING.value
    )
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("group_id", "invitee_id", name="uq_group_invitation_target"),
        CheckConstraint("inviter_id <> invitee_id", name="ck_invitation_not_self"),
    )
