"""Community contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel
from app.schemas.social import PublicUserResponse

# A small, curated set of topics and reactions — free-form categories would fragment a small
# community, and free-form reaction text is a moderation surface we do not need.
PostTopic = Literal[
    "general",
    "motivation",
    "study_tips",
    "resources",
    "wins",
    "accountability",
    "questions",
]
PostReactionEmoji = Literal["like", "insightful", "celebrate", "support", "curious"]


class CreatePostRequest(StrictModel):
    topic: PostTopic = "general"
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class CreateCommentRequest(StrictModel):
    body: str = Field(min_length=1, max_length=2000)


class ReactToPostRequest(StrictModel):
    emoji: PostReactionEmoji


class PostResponse(ResponseModel):
    id: uuid.UUID
    author: PublicUserResponse
    topic: str
    title: str
    body: str
    created_at: datetime
    comment_count: int
    reaction_count: int
    my_reaction: str | None = None
    bookmarked: bool = False


class CommentResponse(ResponseModel):
    id: uuid.UUID
    author: PublicUserResponse
    body: str
    created_at: datetime


class PostDetailResponse(ResponseModel):
    post: PostResponse
    comments: list[CommentResponse]
