"""Presence routes: heartbeat in, live snapshots out.

The snapshot endpoints are the durable path — a client polls them on a timer and also when a
WebSocket drops. Presence itself is ephemeral and privacy-filtered before it is ever stored.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, PresenceServiceDep, RealtimeServiceDep
from app.domain.social.presence import PresenceState
from app.schemas.presence import HeartbeatRequest, PresenceResponse

router = APIRouter(prefix="/presence", tags=["presence"])


@router.put(
    "/heartbeat",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Report my current presence",
)
async def heartbeat(
    payload: HeartbeatRequest,
    user: CurrentUser,
    presence: PresenceServiceDep,
    realtime: RealtimeServiceDep,
) -> None:
    await presence.heartbeat(
        user=user,
        state=PresenceState(payload.state),
        subject_id=payload.subject_id,
        started_at=payload.started_at,
    )
    # Nudge watchers to refresh — but only if the user is actually broadcasting.
    if user.settings.privacy_show_presence:
        await realtime.publish_presence(user, payload.state)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Go offline")
async def go_offline(
    user: CurrentUser, presence: PresenceServiceDep, realtime: RealtimeServiceDep
) -> None:
    await presence.clear(user.id)
    await realtime.publish_presence(user, "offline")


@router.get("/friends", response_model=list[PresenceResponse], summary="Friends studying now")
async def friends_presence(
    user: CurrentUser, presence: PresenceServiceDep
) -> list[PresenceResponse]:
    rows = await presence.friends_presence(user)
    return [PresenceResponse.model_validate(row) for row in rows]


@router.get(
    "/groups/{group_id}",
    response_model=list[PresenceResponse],
    summary="Group members studying now",
)
async def group_presence(
    group_id: uuid.UUID, user: CurrentUser, presence: PresenceServiceDep
) -> list[PresenceResponse]:
    rows = await presence.group_presence(user, group_id)
    return [PresenceResponse.model_validate(row) for row in rows]
