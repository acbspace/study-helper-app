"""Moderation reports, the in-app notification inbox, and push-token registration."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentUser,
    DeviceDep,
    ExportServiceDep,
    NotificationServiceDep,
    ReportServiceDep,
)
from app.api.rate_limit import social_rate_limit
from app.schemas.platform import (
    CreateReportRequest,
    NotificationResponse,
    PushTokenRequest,
    ReportResponse,
    UnreadCountResponse,
)

router = APIRouter(tags=["platform"])


@router.post(
    "/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a user or group",
    dependencies=[Depends(social_rate_limit)],
)
async def create_report(
    payload: CreateReportRequest, user: CurrentUser, reports: ReportServiceDep
) -> ReportResponse:
    report = await reports.create(
        reporter_id=user.id,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        reason=payload.reason,
    )
    return ReportResponse.model_validate(report)


@router.get("/reports", response_model=list[ReportResponse], summary="List my reports")
async def list_reports(user: CurrentUser, reports: ReportServiceDep) -> list[ReportResponse]:
    rows = await reports.list_mine(user.id)
    return [ReportResponse.model_validate(row) for row in rows]


@router.get(
    "/notifications", response_model=list[NotificationResponse], summary="List notifications"
)
async def list_notifications(
    user: CurrentUser,
    notifications: NotificationServiceDep,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[NotificationResponse]:
    rows = await notifications.list_for(user.id, limit=limit, unread_only=unread_only)
    return [NotificationResponse.model_validate(row) for row in rows]


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCountResponse,
    summary="Count unread notifications",
)
async def unread_count(
    user: CurrentUser, notifications: NotificationServiceDep
) -> UnreadCountResponse:
    return UnreadCountResponse(unread=await notifications.unread_count(user.id))


@router.post(
    "/notifications/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark every notification read",
)
async def mark_all_read(user: CurrentUser, notifications: NotificationServiceDep) -> None:
    await notifications.mark_all_read(user.id)


@router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark a notification read",
)
async def mark_read(
    notification_id: uuid.UUID, user: CurrentUser, notifications: NotificationServiceDep
) -> NotificationResponse:
    row = await notifications.mark_read(user_id=user.id, notification_id=notification_id)
    return NotificationResponse.model_validate(row)


@router.get("/me/export", summary="Export all my data")
async def export_my_data(user: CurrentUser, export: ExportServiceDep) -> dict[str, Any]:
    """A portable JSON copy of everything the user created."""
    return await export.export(user)


@router.put(
    "/me/push-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Register this device for push",
)
async def register_push_token(
    payload: PushTokenRequest,
    user: CurrentUser,
    device_id: DeviceDep,
    notifications: NotificationServiceDep,
) -> None:
    await notifications.register_push_token(
        user_id=user.id, device_id=device_id, token=payload.token, platform=payload.platform
    )
