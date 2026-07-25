"""Friendship and user-search contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.common import ResponseModel, StrictModel


class SendFriendRequestRequest(StrictModel):
    """Address a friend request by user id or by username — exactly one of them."""

    user_id: uuid.UUID | None = None
    username: str | None = Field(default=None, min_length=1, max_length=30)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> SendFriendRequestRequest:
        if (self.user_id is None) == (self.username is None):
            raise ValueError("Provide exactly one of user_id or username.")
        return self


class BlockUserRequest(StrictModel):
    user_id: uuid.UUID


class PublicUserResponse(ResponseModel):
    """A safe public projection of another user; never exposes their email."""

    id: uuid.UUID
    username: str
    display_name: str
    avatar_url: str | None = None
    country_code: str | None = None
    study_category: str


class FriendResponse(ResponseModel):
    friendship_id: uuid.UUID
    user: PublicUserResponse
    since: datetime | None = None


class FriendRequestResponse(ResponseModel):
    friendship_id: uuid.UUID
    direction: str
    status: str
    user: PublicUserResponse
    created_at: datetime


class FriendRequestsResponse(ResponseModel):
    incoming: list[FriendRequestResponse]
    outgoing: list[FriendRequestResponse]


class SearchResultResponse(ResponseModel):
    user: PublicUserResponse
    relationship: str
    friendship_id: uuid.UUID | None = None
