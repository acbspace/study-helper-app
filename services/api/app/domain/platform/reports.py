"""Moderation reports.

Reports are evidence, not enforcement: filing one records the claim for a human to review
and never itself removes content or punishes anyone (docs/architecture/SECURITY.md). A
reporter may hold one *open* report per subject, which keeps the queue meaningful without
silently swallowing repeat concerns — reopening happens when a moderator resolves the first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ErrorCode, NotFoundError
from app.models.community import CommunityComment, CommunityPost
from app.models.enums import ReportStatus, ReportSubjectType
from app.models.platform import Report
from app.models.social import StudyGroup
from app.models.user import User


class ReportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        reporter_id: uuid.UUID,
        subject_type: str,
        subject_id: uuid.UUID,
        reason: str,
    ) -> Report:
        await self._require_subject(reporter_id, subject_type, subject_id)

        existing = await self._db.execute(
            select(Report).where(
                Report.reporter_id == reporter_id,
                Report.subject_type == subject_type,
                Report.subject_id == subject_id,
                Report.status == ReportStatus.OPEN.value,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(
                ErrorCode.REPORT_EXISTS,
                "You have already reported this; it is awaiting review.",
            )

        report = Report(
            reporter_id=reporter_id,
            subject_type=subject_type,
            subject_id=subject_id,
            reason=reason.strip(),
            status=ReportStatus.OPEN.value,
        )
        self._db.add(report)
        await self._db.commit()
        await self._db.refresh(report)
        return report

    async def list_mine(self, reporter_id: uuid.UUID, *, limit: int = 50) -> list[Report]:
        result = await self._db.execute(
            select(Report)
            .where(Report.reporter_id == reporter_id)
            .order_by(Report.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _require_subject(
        self, reporter_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID
    ) -> None:
        """The subject must exist, so the moderation queue never fills with dangling ids."""
        if subject_type == ReportSubjectType.USER.value:
            if subject_id == reporter_id:
                raise AppError(ErrorCode.CANNOT_REPORT_SELF, "You cannot report yourself.")
            found = await self._db.execute(
                select(User.id).where(User.id == subject_id, User.deleted_at.is_(None))
            )
            if found.first() is None:
                raise NotFoundError(ErrorCode.USER_NOT_FOUND, "User not found.")
        elif subject_type == ReportSubjectType.GROUP.value:
            found = await self._db.execute(
                select(StudyGroup.id).where(
                    StudyGroup.id == subject_id, StudyGroup.deleted_at.is_(None)
                )
            )
            if found.first() is None:
                raise NotFoundError(ErrorCode.GROUP_NOT_FOUND, "Group not found.")
        elif subject_type == ReportSubjectType.POST.value:
            found = await self._db.execute(
                select(CommunityPost.id).where(
                    CommunityPost.id == subject_id, CommunityPost.deleted_at.is_(None)
                )
            )
            if found.first() is None:
                raise NotFoundError(ErrorCode.POST_NOT_FOUND, "Post not found.")
        elif subject_type == ReportSubjectType.COMMENT.value:
            found = await self._db.execute(
                select(CommunityComment.id).where(
                    CommunityComment.id == subject_id, CommunityComment.deleted_at.is_(None)
                )
            )
            if found.first() is None:
                raise NotFoundError(ErrorCode.COMMENT_NOT_FOUND, "Comment not found.")
        else:  # pragma: no cover - the schema constrains this to the known subject types
            raise AppError(ErrorCode.VALIDATION_ERROR, "Unsupported report subject.")
