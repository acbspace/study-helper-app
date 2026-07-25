"""Community: topic posts, comments, reactions, and bookmarks.

Moderation-first: posts and comments are **soft-deleted** (`deleted_at`), never hard-deleted,
so a removed item can still be reviewed and its reports keep pointing at something real. Every
read path filters `deleted_at IS NULL`, so a deleted item simply disappears from the feed.

Counts (comments, reactions) are computed from these tables rather than denormalised — correct
by construction, and the community's volume does not justify the cache-invalidation risk.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UtcDateTime, UuidType


class CommunityPost(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "community_posts"

    author_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    comments: Mapped[list[CommunityComment]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_community_posts_topic_created", "topic", "created_at"),)


class CommunityComment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "community_comments"

    post_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    post: Mapped[CommunityPost] = relationship(back_populates="comments")


class CommunityReaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One reaction per user per post — reacting again just changes the emoji."""

    __tablename__ = "community_reactions"

    post_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_community_reaction_user"),)


class CommunityBookmark(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "community_bookmarks"

    post_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("community_posts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_community_bookmark_user"),)
