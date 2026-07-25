"""Study-group contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ResponseModel, StrictModel
from app.schemas.social import PublicUserResponse

Visibility = Literal["public", "private", "invite"]
ManageableRole = Literal["moderator", "member"]


class CreateGroupRequest(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    rules: str | None = Field(default=None, max_length=2000)
    visibility: Visibility = "public"
    max_members: int = Field(default=50, ge=2, le=500)


class UpdateGroupRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=500)
    rules: str | None = Field(default=None, max_length=2000)
    visibility: Visibility | None = None
    max_members: int | None = Field(default=None, ge=2, le=500)


class JoinByCodeRequest(StrictModel):
    invite_code: str = Field(min_length=1, max_length=12)


class InviteToGroupRequest(StrictModel):
    user_id: uuid.UUID


class SetMemberRoleRequest(StrictModel):
    role: ManageableRole


class GroupSummaryResponse(ResponseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    visibility: str
    member_count: int
    max_members: int
    owner: PublicUserResponse
    created_at: datetime
    my_role: str | None = None


class GroupMemberResponse(ResponseModel):
    user: PublicUserResponse
    role: str
    joined_at: datetime


class GroupDetailResponse(ResponseModel):
    group: GroupSummaryResponse
    rules: str | None = None
    members: list[GroupMemberResponse]
    invite_code: str | None = None


class GroupInvitationResponse(ResponseModel):
    id: uuid.UUID
    group: GroupSummaryResponse
    inviter: PublicUserResponse
    expires_at: datetime
    created_at: datetime
