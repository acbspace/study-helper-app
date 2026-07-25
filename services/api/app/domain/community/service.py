"""Community posts, comments, reactions, and bookmarks.

Everything here treats deletion as soft: an author removing their post hides it from every
feed but keeps the row, so a report filed against it still resolves and a moderator can see
what was said. Counts are read from the tables on demand, so they can never drift from
reality.

Authorship is the only permission a user has over content: you can delete your own post or
comment, react and bookmark anyone's. Moderation beyond that (removing others' content) is a
future admin surface — for now the lever users have against bad content is the report.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.errors import ErrorCode, ForbiddenError, NotFoundError
from app.domain.social.service import PublicUserView, load_public_users
from app.models.community import (
    CommunityBookmark,
    CommunityComment,
    CommunityPost,
    CommunityReaction,
)

DEFAULT_PAGE = 20


@dataclass(frozen=True, slots=True)
class PostView:
    id: uuid.UUID
    author: PublicUserView
    topic: str
    title: str
    body: str
    created_at: datetime
    comment_count: int
    reaction_count: int
    my_reaction: str | None
    bookmarked: bool


@dataclass(frozen=True, slots=True)
class CommentView:
    id: uuid.UUID
    author: PublicUserView
    body: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PostDetailView:
    post: PostView
    comments: list[CommentView]


class CommunityService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------ posts

    async def create_post(
        self, *, author_id: uuid.UUID, topic: str, title: str, body: str
    ) -> PostView:
        post = CommunityPost(
            author_id=author_id, topic=topic.strip(), title=title.strip(), body=body.strip()
        )
        self._db.add(post)
        await self._db.commit()
        await self._db.refresh(post)
        return (await self._post_views(author_id, [post]))[0]

    async def list_posts(
        self,
        *,
        viewer_id: uuid.UUID,
        topic: str | None = None,
        limit: int = DEFAULT_PAGE,
    ) -> list[PostView]:
        query = self._live_posts()
        if topic:
            query = query.where(CommunityPost.topic == topic.strip())
        query = query.order_by(CommunityPost.created_at.desc()).limit(limit)
        posts = list((await self._db.execute(query)).scalars().all())
        return await self._post_views(viewer_id, posts)

    async def get_post(self, *, viewer_id: uuid.UUID, post_id: uuid.UUID) -> PostDetailView:
        post = await self._require_post(post_id)
        view = (await self._post_views(viewer_id, [post]))[0]
        comments = await self._comments(post_id)
        return PostDetailView(post=view, comments=comments)

    async def delete_post(self, *, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        post = await self._require_post(post_id)
        if post.author_id != user_id:
            raise ForbiddenError("You can only delete your own posts.")
        post.deleted_at = utc_now()
        await self._db.commit()

    # ------------------------------------------------------------------ comments

    async def add_comment(
        self, *, author_id: uuid.UUID, post_id: uuid.UUID, body: str
    ) -> CommentView:
        await self._require_post(post_id)
        comment = CommunityComment(post_id=post_id, author_id=author_id, body=body.strip())
        self._db.add(comment)
        await self._db.commit()
        await self._db.refresh(comment)
        authors = await load_public_users(self._db, {author_id})
        return CommentView(
            id=comment.id,
            author=authors[author_id],
            body=comment.body,
            created_at=comment.created_at,
        )

    async def delete_comment(self, *, user_id: uuid.UUID, comment_id: uuid.UUID) -> None:
        result = await self._db.execute(
            select(CommunityComment).where(
                CommunityComment.id == comment_id, CommunityComment.deleted_at.is_(None)
            )
        )
        comment = result.scalar_one_or_none()
        if comment is None:
            raise NotFoundError(ErrorCode.COMMENT_NOT_FOUND, "Comment not found.")
        if comment.author_id != user_id:
            raise ForbiddenError("You can only delete your own comments.")
        comment.deleted_at = utc_now()
        await self._db.commit()

    # ------------------------------------------------------------------ reactions

    async def react(self, *, user_id: uuid.UUID, post_id: uuid.UUID, emoji: str) -> None:
        await self._require_post(post_id)
        existing = await self._db.execute(
            select(CommunityReaction).where(
                CommunityReaction.post_id == post_id, CommunityReaction.user_id == user_id
            )
        )
        reaction = existing.scalar_one_or_none()
        if reaction is None:
            self._db.add(CommunityReaction(post_id=post_id, user_id=user_id, emoji=emoji))
        else:
            reaction.emoji = emoji
        try:
            await self._db.commit()
        except IntegrityError:  # lost a race on the unique (post, user) index
            await self._db.rollback()

    async def unreact(self, *, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        await self._db.execute(
            delete(CommunityReaction).where(
                CommunityReaction.post_id == post_id, CommunityReaction.user_id == user_id
            )
        )
        await self._db.commit()

    # ------------------------------------------------------------------ bookmarks

    async def bookmark(self, *, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        await self._require_post(post_id)
        self._db.add(CommunityBookmark(post_id=post_id, user_id=user_id))
        try:
            await self._db.commit()
        except IntegrityError:  # already bookmarked — idempotent
            await self._db.rollback()

    async def unbookmark(self, *, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        await self._db.execute(
            delete(CommunityBookmark).where(
                CommunityBookmark.post_id == post_id, CommunityBookmark.user_id == user_id
            )
        )
        await self._db.commit()

    async def list_bookmarks(
        self, *, user_id: uuid.UUID, limit: int = DEFAULT_PAGE
    ) -> list[PostView]:
        query = (
            self._live_posts()
            .join(CommunityBookmark, CommunityBookmark.post_id == CommunityPost.id)
            .where(CommunityBookmark.user_id == user_id)
            .order_by(CommunityBookmark.created_at.desc())
            .limit(limit)
        )
        posts = list((await self._db.execute(query)).scalars().all())
        return await self._post_views(user_id, posts)

    # ------------------------------------------------------------------ helpers

    def _live_posts(self) -> Select[tuple[CommunityPost]]:
        return select(CommunityPost).where(CommunityPost.deleted_at.is_(None))

    async def _require_post(self, post_id: uuid.UUID) -> CommunityPost:
        result = await self._db.execute(self._live_posts().where(CommunityPost.id == post_id))
        post = result.scalar_one_or_none()
        if post is None:
            raise NotFoundError(ErrorCode.POST_NOT_FOUND, "Post not found.")
        return post

    async def _post_views(self, viewer_id: uuid.UUID, posts: list[CommunityPost]) -> list[PostView]:
        if not posts:
            return []
        post_ids = [post.id for post in posts]
        authors = await load_public_users(self._db, {post.author_id for post in posts})
        comment_counts = await self._counts(
            select(CommunityComment.post_id, func.count())
            .where(
                CommunityComment.post_id.in_(post_ids),
                CommunityComment.deleted_at.is_(None),
            )
            .group_by(CommunityComment.post_id),
        )
        reaction_counts = await self._counts(
            select(CommunityReaction.post_id, func.count())
            .where(CommunityReaction.post_id.in_(post_ids))
            .group_by(CommunityReaction.post_id),
        )
        my_reactions = await self._my_reactions(viewer_id, post_ids)
        my_bookmarks = await self._my_bookmarks(viewer_id, post_ids)

        views: list[PostView] = []
        for post in posts:
            author = authors.get(post.author_id)
            if author is None:
                continue
            views.append(
                PostView(
                    id=post.id,
                    author=author,
                    topic=post.topic,
                    title=post.title,
                    body=post.body,
                    created_at=post.created_at,
                    comment_count=comment_counts.get(post.id, 0),
                    reaction_count=reaction_counts.get(post.id, 0),
                    my_reaction=my_reactions.get(post.id),
                    bookmarked=post.id in my_bookmarks,
                )
            )
        return views

    async def _comments(self, post_id: uuid.UUID) -> list[CommentView]:
        result = await self._db.execute(
            select(CommunityComment)
            .where(CommunityComment.post_id == post_id, CommunityComment.deleted_at.is_(None))
            .order_by(CommunityComment.created_at)
        )
        comments = list(result.scalars().all())
        authors = await load_public_users(self._db, {c.author_id for c in comments})
        return [
            CommentView(
                id=comment.id,
                author=authors[comment.author_id],
                body=comment.body,
                created_at=comment.created_at,
            )
            for comment in comments
            if comment.author_id in authors
        ]

    async def _counts(self, query: Select[tuple[uuid.UUID, int]]) -> dict[uuid.UUID, int]:
        result = await self._db.execute(query)
        return {post_id: int(count) for post_id, count in result.all()}

    async def _my_reactions(
        self, user_id: uuid.UUID, post_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        result = await self._db.execute(
            select(CommunityReaction.post_id, CommunityReaction.emoji).where(
                CommunityReaction.user_id == user_id,
                CommunityReaction.post_id.in_(post_ids),
            )
        )
        return {row.post_id: row.emoji for row in result.all()}

    async def _my_bookmarks(self, user_id: uuid.UUID, post_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        result = await self._db.execute(
            select(CommunityBookmark.post_id).where(
                CommunityBookmark.user_id == user_id,
                CommunityBookmark.post_id.in_(post_ids),
            )
        )
        return set(result.scalars().all())
