"""Subject routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, SubjectServiceDep
from app.schemas.subjects import (
    CreateSubjectRequest,
    ReorderSubjectsRequest,
    SubjectResponse,
    UpdateSubjectRequest,
)

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("", response_model=list[SubjectResponse], summary="List subjects")
async def list_subjects(
    user: CurrentUser,
    subjects: SubjectServiceDep,
    include_archived: bool = Query(default=False),
) -> list[SubjectResponse]:
    rows = await subjects.list_for_user(user.id, include_archived=include_archived)
    return [SubjectResponse.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=SubjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subject",
)
async def create_subject(
    payload: CreateSubjectRequest, user: CurrentUser, subjects: SubjectServiceDep
) -> SubjectResponse:
    subject = await subjects.create(
        user_id=user.id,
        name=payload.name,
        color_hex=payload.color_hex,
        sort_order=payload.sort_order,
    )
    return SubjectResponse.model_validate(subject)


@router.patch("/{subject_id}", response_model=SubjectResponse, summary="Update a subject")
async def update_subject(
    subject_id: uuid.UUID,
    payload: UpdateSubjectRequest,
    user: CurrentUser,
    subjects: SubjectServiceDep,
) -> SubjectResponse:
    subject = await subjects.update(
        user_id=user.id,
        subject_id=subject_id,
        name=payload.name,
        color_hex=payload.color_hex,
        sort_order=payload.sort_order,
        is_archived=payload.is_archived,
    )
    return SubjectResponse.model_validate(subject)


@router.post("/reorder", response_model=list[SubjectResponse], summary="Reorder subjects")
async def reorder_subjects(
    payload: ReorderSubjectsRequest, user: CurrentUser, subjects: SubjectServiceDep
) -> list[SubjectResponse]:
    rows = await subjects.reorder(user_id=user.id, ordered_ids=payload.subject_ids)
    return [SubjectResponse.model_validate(row) for row in rows]
