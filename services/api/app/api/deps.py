"""Request-scoped dependencies: settings, database session, current user, services."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token, hash_device_identifier
from app.domain.accounts.email import EmailSender, build_email_sender
from app.domain.accounts.service import AccountService
from app.domain.community.service import CommunityService
from app.domain.goals.service import GoalService
from app.domain.league.service import LeagueService
from app.domain.planner.service import PlannerService
from app.domain.platform.export import ExportService
from app.domain.platform.moderation import ModerationService
from app.domain.platform.notifications import NotificationService
from app.domain.platform.reports import ReportService
from app.domain.realtime.broadcaster import Broadcaster
from app.domain.realtime.hub import RealtimeHub
from app.domain.realtime.service import RealtimeService
from app.domain.sessions.integrity import IntegrityThresholds
from app.domain.sessions.service import StudySessionService
from app.domain.social.groups import GroupService
from app.domain.social.presence import PresenceService, PresenceStore, build_presence_store
from app.domain.social.service import FriendshipService
from app.domain.statistics.calendar import resolve_timezone
from app.domain.statistics.service import StatisticsService
from app.domain.subjects.service import SubjectService
from app.models.user import User


def get_settings_for_request(request: Request) -> Settings:
    """Read the settings the application was actually built with.

    Deliberately not `get_settings()`: that returns the process-wide cached instance, so an
    app constructed with explicit settings (tests, multi-tenant hosting) would silently run
    on different configuration than it was given.
    """
    settings: Settings = request.app.state.settings
    return settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


SettingsDep = Annotated[Settings, Depends(get_settings_for_request)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def get_account_service(db: DbDep, settings: SettingsDep) -> AccountService:
    return AccountService(db, settings)


def get_email_sender(settings: SettingsDep) -> EmailSender:
    return build_email_sender(settings)


EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]


def get_subject_service(db: DbDep) -> SubjectService:
    return SubjectService(db)


def get_statistics_service(db: DbDep) -> StatisticsService:
    return StatisticsService(db)


def get_planner_service(db: DbDep) -> PlannerService:
    return PlannerService(db)


def get_goal_service(db: DbDep) -> GoalService:
    return GoalService(db)


def get_community_service(db: DbDep) -> CommunityService:
    return CommunityService(db)


def get_friendship_service(db: DbDep) -> FriendshipService:
    return FriendshipService(db)


def get_group_service(db: DbDep) -> GroupService:
    return GroupService(db)


def get_presence_service(request: Request, db: DbDep) -> PresenceService:
    """Reuse one presence store per app so the in-memory fallback survives across requests."""
    store: PresenceStore | None = getattr(request.app.state, "presence_store", None)
    if store is None:
        store = build_presence_store(getattr(request.app.state, "redis", None))
        request.app.state.presence_store = store
    return PresenceService(db, store)


def get_realtime_hub(app_state: Any) -> RealtimeHub:
    """The one hub per process. Lazily created so tests that skip lifespan still work."""
    hub: RealtimeHub | None = getattr(app_state, "realtime_hub", None)
    if hub is None:
        hub = RealtimeHub()
        app_state.realtime_hub = hub
    return hub


def get_broadcaster(app_state: Any) -> Broadcaster:
    broadcaster: Broadcaster | None = getattr(app_state, "broadcaster", None)
    if broadcaster is None:
        broadcaster = Broadcaster(get_realtime_hub(app_state), getattr(app_state, "redis", None))
        app_state.broadcaster = broadcaster
    return broadcaster


def get_realtime_service(request: Request, db: DbDep) -> RealtimeService:
    return RealtimeService(db, get_broadcaster(request.app.state))


def get_league_service(db: DbDep) -> LeagueService:
    return LeagueService(db)


def get_report_service(db: DbDep) -> ReportService:
    return ReportService(db)


def get_notification_service(db: DbDep) -> NotificationService:
    return NotificationService(db)


def get_export_service(db: DbDep) -> ExportService:
    return ExportService(db)


def get_moderation_service(db: DbDep) -> ModerationService:
    return ModerationService(db)


def get_session_service(db: DbDep, settings: SettingsDep) -> StudySessionService:
    thresholds = IntegrityThresholds(
        max_session_hours=settings.max_session_hours,
        max_single_interval_hours=settings.max_single_interval_hours,
        max_clock_skew_minutes=settings.max_clock_skew_minutes,
        retro_edit_window_hours=settings.retro_edit_window_hours,
    )
    return StudySessionService(db, thresholds)


AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
SubjectServiceDep = Annotated[SubjectService, Depends(get_subject_service)]
StatisticsServiceDep = Annotated[StatisticsService, Depends(get_statistics_service)]
PlannerServiceDep = Annotated[PlannerService, Depends(get_planner_service)]
GoalServiceDep = Annotated[GoalService, Depends(get_goal_service)]
CommunityServiceDep = Annotated[CommunityService, Depends(get_community_service)]
FriendshipServiceDep = Annotated[FriendshipService, Depends(get_friendship_service)]
GroupServiceDep = Annotated[GroupService, Depends(get_group_service)]
PresenceServiceDep = Annotated[PresenceService, Depends(get_presence_service)]
RealtimeServiceDep = Annotated[RealtimeService, Depends(get_realtime_service)]
LeagueServiceDep = Annotated[LeagueService, Depends(get_league_service)]
ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
ExportServiceDep = Annotated[ExportService, Depends(get_export_service)]
ModerationServiceDep = Annotated[ModerationService, Depends(get_moderation_service)]
SessionServiceDep = Annotated[StudySessionService, Depends(get_session_service)]


async def get_current_user(
    accounts: AccountServiceDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the caller from a bearer token.

    Every private route depends on this; there is no code path that reads a user id
    straight from the request body.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Authentication required.", status_code=401)
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_access_token(settings, token)

    user = await accounts.get_user(user_id)
    if user is None or not user.is_active:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Authentication required.", status_code=401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin(user: CurrentUser) -> User:
    """A moderator. Non-admins are told 'not found', not 'forbidden', so the admin surface
    does not even confirm it exists to ordinary users."""
    if not user.is_admin:
        raise AppError(ErrorCode.NOT_PERMITTED, "Not found.", status_code=404)
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]


def get_user_timezone(user: CurrentUser) -> ZoneInfo:
    return resolve_timezone(user.settings.timezone)


UserTimezone = Annotated[ZoneInfo, Depends(get_user_timezone)]


async def get_device_id(
    settings: SettingsDep,
    db: DbDep,
    user: CurrentUser,
    x_device_id: Annotated[str | None, Header()] = None,
) -> uuid.UUID | None:
    """Resolve (and upsert) the calling device, storing only a salted hash."""
    if not x_device_id:
        return None

    from sqlalchemy import select

    from app.core.clock import utc_now
    from app.models.user import Device

    device_hash = hash_device_identifier(settings, x_device_id)
    result = await db.execute(
        select(Device).where(Device.user_id == user.id, Device.device_hash == device_hash)
    )
    device = result.scalar_one_or_none()
    if device is None:
        device = Device(user_id=user.id, device_hash=device_hash, platform="unknown")
        db.add(device)
    device.last_seen_at = utc_now()
    await db.commit()
    await db.refresh(device)
    return device.id


DeviceDep = Annotated[uuid.UUID | None, Depends(get_device_id)]
