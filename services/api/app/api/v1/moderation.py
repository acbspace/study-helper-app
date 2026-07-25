"""Moderator routes: review and resolve reports. Admin-only.

The whole surface is gated on `CurrentAdmin`, which 404s for non-moderators — an ordinary
user cannot even tell these endpoints exist.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdmin, ModerationServiceDep
from app.domain.platform.moderation import ReportView
from app.schemas.platform import ModerationReportResponse, ResolveReportRequest

router = APIRouter(prefix="/admin", tags=["moderation"])


def _response(view: ReportView) -> ModerationReportResponse:
    return ModerationReportResponse.model_validate(view)


@router.get(
    "/reports",
    response_model=list[ModerationReportResponse],
    summary="Review the report queue",
)
async def list_reports(
    admin: CurrentAdmin,
    moderation: ModerationServiceDep,
    status: str | None = Query(default=None, pattern="^(open|actioned|dismissed)$"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ModerationReportResponse]:
    rows = await moderation.list_reports(status=status, limit=limit)
    return [_response(row) for row in rows]


@router.post(
    "/reports/{report_id}/resolve",
    response_model=ModerationReportResponse,
    summary="Resolve a report",
)
async def resolve_report(
    report_id: uuid.UUID,
    payload: ResolveReportRequest,
    admin: CurrentAdmin,
    moderation: ModerationServiceDep,
) -> ModerationReportResponse:
    view = await moderation.resolve(
        moderator=admin,
        report_id=report_id,
        decision=payload.decision,
        remove_content=payload.remove_content,
        note=payload.note,
    )
    return _response(view)
