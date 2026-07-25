"""The moderator review queue.

A report is a claim; this is where a human decides what to do with it. Two things are kept
honest here: every resolution is written to the append-only audit log (who did what, when,
and why), and removing content **soft-deletes** it — the row survives so the decision stays
reviewable and other reports against it still resolve.

Resolving a report that led to content removal also closes the sibling reports against the
same subject, so ten people flagging one bad post become one decision, not ten.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utc_now
from app.core.errors import ErrorCode, NotFoundError
from app.domain.audit import record_audit
from app.domain.social.service import PublicUserView, load_public_users
from app.models.community import CommunityComment, CommunityPost
from app.models.enums import ActorType, ReportStatus, ReportSubjectType
from app.models.platform import Report
from app.models.social import StudyGroup
from app.models.user import User, UserProfile

_REMOVABLE = {ReportSubjectType.POST.value, ReportSubjectType.COMMENT.value}


@dataclass(frozen=True, slots=True)
class ReportView:
    id: uuid.UUID
    reporter: PublicUserView | None
    subject_type: str
    subject_id: uuid.UUID
    subject_preview: str | None
    reason: str
    status: str
    resolution_note: str | None
    created_at: datetime
    resolved_at: datetime | None


class ModerationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_reports(self, *, status: str | None = None, limit: int = 50) -> list[ReportView]:
        query = select(Report)
        if status is not None:
            query = query.where(Report.status == status)
        query = query.order_by(Report.created_at.desc()).limit(limit)
        reports = list((await self._db.execute(query)).scalars().all())

        reporters = await load_public_users(self._db, {r.reporter_id for r in reports})
        previews = await self._subject_previews(reports)
        return [self._view(report, reporters, previews) for report in reports]

    async def resolve(
        self,
        *,
        moderator: User,
        report_id: uuid.UUID,
        decision: str,
        remove_content: bool,
        note: str | None,
    ) -> ReportView:
        result = await self._db.execute(
            select(Report).where(Report.id == report_id, Report.status == ReportStatus.OPEN.value)
        )
        report = result.scalar_one_or_none()
        if report is None:
            raise NotFoundError(ErrorCode.REPORT_NOT_FOUND, "No open report found.")

        now = utc_now()
        actioned = decision == "action"
        removed = actioned and remove_content and report.subject_type in _REMOVABLE

        if removed:
            await self._remove_subject(moderator, report, now)
            # One decision closes every open report against the same content.
            await self._close_siblings(report, note, now)

        report.status = ReportStatus.ACTIONED.value if actioned else ReportStatus.DISMISSED.value
        report.resolved_at = now
        report.resolution_note = note

        await record_audit(
            self._db,
            actor_type=ActorType.ADMIN,
            actor_id=moderator.id,
            action="report.resolved",
            entity_type="report",
            entity_id=report.id,
            before={"status": ReportStatus.OPEN.value},
            after={"status": report.status, "content_removed": removed},
            reason=note,
            now=now,
        )
        await self._db.commit()

        reporters = await load_public_users(self._db, {report.reporter_id})
        previews = await self._subject_previews([report])
        return self._view(report, reporters, previews)

    # ------------------------------------------------------------------ helpers

    async def _remove_subject(self, moderator: User, report: Report, now: datetime) -> None:
        subject: CommunityPost | CommunityComment | None
        if report.subject_type == ReportSubjectType.POST.value:
            subject = (
                await self._db.execute(
                    select(CommunityPost).where(CommunityPost.id == report.subject_id)
                )
            ).scalar_one_or_none()
        else:
            subject = (
                await self._db.execute(
                    select(CommunityComment).where(CommunityComment.id == report.subject_id)
                )
            ).scalar_one_or_none()
        if subject is None or subject.deleted_at is not None:
            return
        subject.deleted_at = now
        await record_audit(
            self._db,
            actor_type=ActorType.ADMIN,
            actor_id=moderator.id,
            action="content.removed",
            entity_type=report.subject_type,
            entity_id=report.subject_id,
            reason="Removed via report review",
            now=now,
        )

    async def _close_siblings(self, report: Report, note: str | None, now: datetime) -> None:
        result = await self._db.execute(
            select(Report).where(
                Report.subject_type == report.subject_type,
                Report.subject_id == report.subject_id,
                Report.status == ReportStatus.OPEN.value,
                Report.id != report.id,
            )
        )
        for sibling in result.scalars().all():
            sibling.status = ReportStatus.ACTIONED.value
            sibling.resolved_at = now
            sibling.resolution_note = note

    async def _subject_previews(self, reports: list[Report]) -> dict[tuple[str, uuid.UUID], str]:
        by_type: dict[str, set[uuid.UUID]] = {}
        for report in reports:
            by_type.setdefault(report.subject_type, set()).add(report.subject_id)

        previews: dict[tuple[str, uuid.UUID], str] = {}
        for subject_type, ids in by_type.items():
            for subject_id, text in (await self._load_previews(subject_type, ids)).items():
                previews[(subject_type, subject_id)] = text
        return previews

    async def _load_previews(self, subject_type: str, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        if subject_type == ReportSubjectType.USER.value:
            rows = await self._db.execute(
                select(UserProfile.user_id, UserProfile.username).where(
                    UserProfile.user_id.in_(ids)
                )
            )
            return {user_id: f"@{username}" for user_id, username in rows.all()}
        if subject_type == ReportSubjectType.GROUP.value:
            rows = await self._db.execute(
                select(StudyGroup.id, StudyGroup.name).where(StudyGroup.id.in_(ids))
            )
            return {row[0]: row[1] for row in rows.all()}
        if subject_type == ReportSubjectType.POST.value:
            rows = await self._db.execute(
                select(CommunityPost.id, CommunityPost.title).where(CommunityPost.id.in_(ids))
            )
            return {row[0]: row[1] for row in rows.all()}
        if subject_type == ReportSubjectType.COMMENT.value:
            rows = await self._db.execute(
                select(CommunityComment.id, CommunityComment.body).where(
                    CommunityComment.id.in_(ids)
                )
            )
            return {comment_id: _snippet(body) for comment_id, body in rows.all()}
        return {}

    @staticmethod
    def _view(
        report: Report,
        reporters: dict[uuid.UUID, PublicUserView],
        previews: dict[tuple[str, uuid.UUID], str],
    ) -> ReportView:
        return ReportView(
            id=report.id,
            reporter=reporters.get(report.reporter_id),
            subject_type=report.subject_type,
            subject_id=report.subject_id,
            subject_preview=previews.get((report.subject_type, report.subject_id)),
            reason=report.reason,
            status=report.status,
            resolution_note=report.resolution_note,
            created_at=report.created_at,
            resolved_at=report.resolved_at,
        )


def _snippet(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
