"""Version 1 of the public API."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    community,
    friends,
    goals,
    groups,
    health,
    league,
    moderation,
    planner,
    platform,
    presence,
    realtime,
    sessions,
    statistics,
    subjects,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(subjects.router)
api_router.include_router(sessions.router)
api_router.include_router(statistics.router)
api_router.include_router(planner.router)
api_router.include_router(goals.router)
api_router.include_router(friends.router)
api_router.include_router(users.router)
api_router.include_router(groups.router)
api_router.include_router(presence.router)
api_router.include_router(realtime.router)
api_router.include_router(platform.router)
api_router.include_router(league.router)
api_router.include_router(community.router)
api_router.include_router(moderation.router)

__all__ = ["api_router"]
