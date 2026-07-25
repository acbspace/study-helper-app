"""Friend graph routes: requests, acceptance, removal, and blocking."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, FriendshipServiceDep, NotificationServiceDep
from app.api.rate_limit import social_rate_limit
from app.models.enums import NotificationKind
from app.schemas.social import (
    BlockUserRequest,
    FriendRequestResponse,
    FriendRequestsResponse,
    FriendResponse,
    PublicUserResponse,
    SendFriendRequestRequest,
)

router = APIRouter(prefix="/friends", tags=["friends"])


@router.get("", response_model=list[FriendResponse], summary="List friends")
async def list_friends(user: CurrentUser, friends: FriendshipServiceDep) -> list[FriendResponse]:
    rows = await friends.list_friends(user.id)
    return [FriendResponse.model_validate(row) for row in rows]


@router.get("/requests", response_model=FriendRequestsResponse, summary="List pending requests")
async def list_requests(user: CurrentUser, friends: FriendshipServiceDep) -> FriendRequestsResponse:
    requests = await friends.list_requests(user.id)
    return FriendRequestsResponse.model_validate(requests)


@router.post(
    "/requests",
    response_model=FriendRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a friend request",
    dependencies=[Depends(social_rate_limit)],
)
async def send_request(
    payload: SendFriendRequestRequest,
    user: CurrentUser,
    friends: FriendshipServiceDep,
    notifications: NotificationServiceDep,
) -> FriendRequestResponse:
    request = await friends.send_request(
        requester=user, addressee_id=payload.user_id, username=payload.username
    )
    if request.status == "pending":
        await notifications.create(
            user_id=request.user.id,
            kind=NotificationKind.FRIEND_REQUEST,
            title="New friend request",
            body=f"{user.profile.display_name} wants to be study friends.",
            data={"friendship_id": str(request.friendship_id), "user_id": str(user.id)},
        )
    return FriendRequestResponse.model_validate(request)


@router.post(
    "/requests/{friendship_id}/accept",
    response_model=FriendResponse,
    summary="Accept a friend request",
)
async def accept_request(
    friendship_id: uuid.UUID,
    user: CurrentUser,
    friends: FriendshipServiceDep,
    notifications: NotificationServiceDep,
) -> FriendResponse:
    friend = await friends.accept(user_id=user.id, friendship_id=friendship_id)
    await notifications.create(
        user_id=friend.user.id,
        kind=NotificationKind.FRIEND_REQUEST,
        title="Friend request accepted",
        body=f"{user.profile.display_name} accepted your friend request.",
        data={"friendship_id": str(friend.friendship_id), "user_id": str(user.id)},
    )
    return FriendResponse.model_validate(friend)


@router.post(
    "/requests/{friendship_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline a friend request",
)
async def decline_request(
    friendship_id: uuid.UUID, user: CurrentUser, friends: FriendshipServiceDep
) -> None:
    await friends.decline(user_id=user.id, friendship_id=friendship_id)


@router.delete(
    "/{friendship_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a request or remove a friend",
)
async def remove_friendship(
    friendship_id: uuid.UUID, user: CurrentUser, friends: FriendshipServiceDep
) -> None:
    await friends.remove(user_id=user.id, friendship_id=friendship_id)


@router.get("/blocked", response_model=list[PublicUserResponse], summary="List blocked users")
async def list_blocked(
    user: CurrentUser, friends: FriendshipServiceDep
) -> list[PublicUserResponse]:
    rows = await friends.list_blocked(user.id)
    return [PublicUserResponse.model_validate(row) for row in rows]


@router.post("/blocks", status_code=status.HTTP_204_NO_CONTENT, summary="Block a user")
async def block_user(
    payload: BlockUserRequest, user: CurrentUser, friends: FriendshipServiceDep
) -> None:
    await friends.block(user_id=user.id, target_id=payload.user_id)


@router.delete(
    "/blocks/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Unblock a user"
)
async def unblock_user(
    user_id: uuid.UUID, user: CurrentUser, friends: FriendshipServiceDep
) -> None:
    await friends.unblock(user_id=user.id, target_id=user_id)
