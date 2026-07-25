"""Community routes: topic posts, comments, reactions, and bookmarks."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CommunityServiceDep, CurrentUser
from app.api.rate_limit import social_rate_limit
from app.domain.community.service import CommentView, PostDetailView, PostView
from app.schemas.community import (
    CommentResponse,
    CreateCommentRequest,
    CreatePostRequest,
    PostDetailResponse,
    PostResponse,
    ReactToPostRequest,
)

router = APIRouter(prefix="/community", tags=["community"])


def _post_response(view: PostView) -> PostResponse:
    return PostResponse.model_validate(view)


def _comment_response(view: CommentView) -> CommentResponse:
    return CommentResponse.model_validate(view)


@router.get("/posts", response_model=list[PostResponse], summary="List posts")
async def list_posts(
    user: CurrentUser,
    community: CommunityServiceDep,
    topic: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[PostResponse]:
    rows = await community.list_posts(viewer_id=user.id, topic=topic, limit=limit)
    return [_post_response(row) for row in rows]


@router.post(
    "/posts",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a post",
    dependencies=[Depends(social_rate_limit)],
)
async def create_post(
    payload: CreatePostRequest, user: CurrentUser, community: CommunityServiceDep
) -> PostResponse:
    view = await community.create_post(
        author_id=user.id, topic=payload.topic, title=payload.title, body=payload.body
    )
    return _post_response(view)


@router.get("/bookmarks", response_model=list[PostResponse], summary="My bookmarked posts")
async def list_bookmarks(user: CurrentUser, community: CommunityServiceDep) -> list[PostResponse]:
    rows = await community.list_bookmarks(user_id=user.id)
    return [_post_response(row) for row in rows]


@router.get("/posts/{post_id}", response_model=PostDetailResponse, summary="A post + comments")
async def get_post(
    post_id: uuid.UUID, user: CurrentUser, community: CommunityServiceDep
) -> PostDetailResponse:
    detail: PostDetailView = await community.get_post(viewer_id=user.id, post_id=post_id)
    return PostDetailResponse(
        post=_post_response(detail.post),
        comments=[_comment_response(comment) for comment in detail.comments],
    )


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete my post")
async def delete_post(
    post_id: uuid.UUID, user: CurrentUser, community: CommunityServiceDep
) -> None:
    await community.delete_post(user_id=user.id, post_id=post_id)


@router.post(
    "/posts/{post_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Comment on a post",
    dependencies=[Depends(social_rate_limit)],
)
async def add_comment(
    post_id: uuid.UUID,
    payload: CreateCommentRequest,
    user: CurrentUser,
    community: CommunityServiceDep,
) -> CommentResponse:
    view = await community.add_comment(author_id=user.id, post_id=post_id, body=payload.body)
    return _comment_response(view)


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete my comment",
)
async def delete_comment(
    comment_id: uuid.UUID, user: CurrentUser, community: CommunityServiceDep
) -> None:
    await community.delete_comment(user_id=user.id, comment_id=comment_id)


@router.put(
    "/posts/{post_id}/reaction",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="React to a post",
)
async def react(
    post_id: uuid.UUID,
    payload: ReactToPostRequest,
    user: CurrentUser,
    community: CommunityServiceDep,
) -> None:
    await community.react(user_id=user.id, post_id=post_id, emoji=payload.emoji)


@router.delete(
    "/posts/{post_id}/reaction",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove my reaction",
)
async def unreact(post_id: uuid.UUID, user: CurrentUser, community: CommunityServiceDep) -> None:
    await community.unreact(user_id=user.id, post_id=post_id)


@router.put(
    "/posts/{post_id}/bookmark",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bookmark a post",
)
async def bookmark(post_id: uuid.UUID, user: CurrentUser, community: CommunityServiceDep) -> None:
    await community.bookmark(user_id=user.id, post_id=post_id)


@router.delete(
    "/posts/{post_id}/bookmark",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a bookmark",
)
async def unbookmark(post_id: uuid.UUID, user: CurrentUser, community: CommunityServiceDep) -> None:
    await community.unbookmark(user_id=user.id, post_id=post_id)
