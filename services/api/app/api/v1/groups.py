"""Study-group routes: lifecycle, membership, roles, and invitations.

Literal paths (`/groups/mine`, `/groups/join`, `/groups/invitations`, …) are declared before
the `/{group_id}` routes so a group id can never shadow them.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, GroupServiceDep, NotificationServiceDep
from app.api.rate_limit import social_rate_limit
from app.models.enums import NotificationKind
from app.schemas.groups import (
    CreateGroupRequest,
    GroupDetailResponse,
    GroupInvitationResponse,
    GroupMemberResponse,
    GroupSummaryResponse,
    InviteToGroupRequest,
    JoinByCodeRequest,
    SetMemberRoleRequest,
    UpdateGroupRequest,
)

router = APIRouter(prefix="/groups", tags=["groups"])


@router.post(
    "",
    response_model=GroupDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a group",
    dependencies=[Depends(social_rate_limit)],
)
async def create_group(
    payload: CreateGroupRequest, user: CurrentUser, groups: GroupServiceDep
) -> GroupDetailResponse:
    detail = await groups.create(
        owner=user,
        name=payload.name,
        description=payload.description,
        rules=payload.rules,
        visibility=payload.visibility,
        max_members=payload.max_members,
    )
    return GroupDetailResponse.model_validate(detail)


@router.get("/mine", response_model=list[GroupSummaryResponse], summary="List my groups")
async def list_my_groups(user: CurrentUser, groups: GroupServiceDep) -> list[GroupSummaryResponse]:
    rows = await groups.list_mine(user.id)
    return [GroupSummaryResponse.model_validate(row) for row in rows]


@router.get(
    "/discover",
    response_model=list[GroupSummaryResponse],
    summary="Discover public groups",
)
async def discover_groups(
    user: CurrentUser,
    groups: GroupServiceDep,
    q: str = Query(default="", max_length=60),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[GroupSummaryResponse]:
    rows = await groups.discover(user_id=user.id, query=q, limit=limit)
    return [GroupSummaryResponse.model_validate(row) for row in rows]


@router.post(
    "/join",
    response_model=GroupDetailResponse,
    summary="Join a group with an invite code",
)
async def join_by_code(
    payload: JoinByCodeRequest, user: CurrentUser, groups: GroupServiceDep
) -> GroupDetailResponse:
    detail = await groups.join_by_code(user_id=user.id, invite_code=payload.invite_code)
    return GroupDetailResponse.model_validate(detail)


@router.get(
    "/invitations",
    response_model=list[GroupInvitationResponse],
    summary="List my group invitations",
)
async def list_invitations(
    user: CurrentUser, groups: GroupServiceDep
) -> list[GroupInvitationResponse]:
    rows = await groups.list_invitations(user.id)
    return [GroupInvitationResponse.model_validate(row) for row in rows]


@router.post(
    "/invitations/{invitation_id}/accept",
    response_model=GroupDetailResponse,
    summary="Accept a group invitation",
)
async def accept_invitation(
    invitation_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep
) -> GroupDetailResponse:
    detail = await groups.respond_invitation(
        user_id=user.id, invitation_id=invitation_id, accept=True
    )
    # accept always yields a detail (respond_invitation only returns None on decline).
    assert detail is not None
    return GroupDetailResponse.model_validate(detail)


@router.post(
    "/invitations/{invitation_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline a group invitation",
)
async def decline_invitation(
    invitation_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep
) -> None:
    await groups.respond_invitation(user_id=user.id, invitation_id=invitation_id, accept=False)


@router.get("/{group_id}", response_model=GroupDetailResponse, summary="Group detail")
async def get_group(
    group_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep
) -> GroupDetailResponse:
    detail = await groups.get_detail(user_id=user.id, group_id=group_id)
    return GroupDetailResponse.model_validate(detail)


@router.patch("/{group_id}", response_model=GroupDetailResponse, summary="Update a group")
async def update_group(
    group_id: uuid.UUID,
    payload: UpdateGroupRequest,
    user: CurrentUser,
    groups: GroupServiceDep,
) -> GroupDetailResponse:
    detail = await groups.update(
        user_id=user.id,
        group_id=group_id,
        name=payload.name,
        description=payload.description,
        rules=payload.rules,
        visibility=payload.visibility,
        max_members=payload.max_members,
    )
    return GroupDetailResponse.model_validate(detail)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a group")
async def delete_group(group_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep) -> None:
    await groups.delete(user_id=user.id, group_id=group_id)


@router.post("/{group_id}/join", response_model=GroupDetailResponse, summary="Join a public group")
async def join_group(
    group_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep
) -> GroupDetailResponse:
    detail = await groups.join_public(user_id=user.id, group_id=group_id)
    return GroupDetailResponse.model_validate(detail)


@router.post("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT, summary="Leave a group")
async def leave_group(group_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep) -> None:
    await groups.leave(user_id=user.id, group_id=group_id)


@router.post(
    "/{group_id}/invitations",
    response_model=GroupInvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to a group",
    dependencies=[Depends(social_rate_limit)],
)
async def invite_to_group(
    group_id: uuid.UUID,
    payload: InviteToGroupRequest,
    user: CurrentUser,
    groups: GroupServiceDep,
    notifications: NotificationServiceDep,
) -> GroupInvitationResponse:
    invitation = await groups.invite(
        actor_id=user.id, group_id=group_id, invitee_id=payload.user_id
    )
    await notifications.create(
        user_id=payload.user_id,
        kind=NotificationKind.GROUP_INVITE,
        title="Group invitation",
        body=f"{user.profile.display_name} invited you to {invitation.group.name}.",
        data={"invitation_id": str(invitation.id), "group_id": str(invitation.group.id)},
    )
    return GroupInvitationResponse.model_validate(invitation)


@router.post(
    "/{group_id}/invite-code/regenerate",
    response_model=GroupDetailResponse,
    summary="Regenerate the invite code",
)
async def regenerate_invite_code(
    group_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep
) -> GroupDetailResponse:
    detail = await groups.regenerate_invite_code(user_id=user.id, group_id=group_id)
    return GroupDetailResponse.model_validate(detail)


@router.patch(
    "/{group_id}/members/{member_id}",
    response_model=GroupMemberResponse,
    summary="Change a member's role",
)
async def set_member_role(
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: SetMemberRoleRequest,
    user: CurrentUser,
    groups: GroupServiceDep,
) -> GroupMemberResponse:
    member = await groups.set_member_role(
        actor_id=user.id, group_id=group_id, target_id=member_id, role=payload.role
    )
    return GroupMemberResponse.model_validate(member)


@router.delete(
    "/{group_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
)
async def remove_member(
    group_id: uuid.UUID, member_id: uuid.UUID, user: CurrentUser, groups: GroupServiceDep
) -> None:
    await groups.remove_member(actor_id=user.id, group_id=group_id, target_id=member_id)
