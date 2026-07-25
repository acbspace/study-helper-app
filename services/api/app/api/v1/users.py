"""User discovery: search other people to add as friends."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, FriendshipServiceDep
from app.schemas.social import SearchResultResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", response_model=list[SearchResultResponse], summary="Search users")
async def search_users(
    user: CurrentUser,
    friends: FriendshipServiceDep,
    q: str = Query(min_length=1, max_length=60, description="Username or display name fragment"),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[SearchResultResponse]:
    results = await friends.search(user_id=user.id, query=q, limit=limit)
    return [SearchResultResponse.model_validate(row) for row in results]
