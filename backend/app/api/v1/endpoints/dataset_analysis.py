"""Profiling, data-quality and cleaning endpoints for a dataset.

Routes stay thin: authorization runs through the shared dependency and the
dataset service, and all computation lives in the profiling/quality/cleaning
services. Every path resolves user -> workspace -> project -> dataset before
touching any data.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.pagination import PageParams
from app.schemas.cleaning import (
    CleaningApplyRequest,
    CleaningApplyResponse,
    CleaningPreviewRequest,
    CleaningPreviewResponse,
    DatasetVersionListResponse,
    DatasetVersionResponse,
)
from app.schemas.common import ErrorResponse
from app.schemas.profiling import DataQualitySummary, DatasetProfile
from app.services import dataset_version_service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}",
    tags=["dataset-analysis"],
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset or version not accessible"},
    422: {"model": ErrorResponse, "description": "Unprocessable file or invalid operation"},
}

#: Optional query parameter shared by profile and quality.
VersionQuery = Query(
    default=None,
    description="Profile a cleaned version instead of the original upload.",
)


@router.get(
    "/profile",
    response_model=DatasetProfile,
    summary="Profile a dataset",
    responses=_RESPONSES,
)
async def get_profile(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> DatasetProfile:
    """Dataset-level and per-column statistics. Deterministic, no LLM."""
    return await dataset_version_service.profile_dataset(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.get(
    "/quality",
    response_model=DataQualitySummary,
    summary="Detect data-quality issues",
    responses=_RESPONSES,
)
async def get_quality(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> DataQualitySummary:
    """Rule-based quality report; the rules applied are returned alongside it."""
    return await dataset_version_service.assess_dataset_quality(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.post(
    "/clean/preview",
    response_model=CleaningPreviewResponse,
    summary="Preview the effect of a cleaning pipeline",
    responses=_RESPONSES,
)
async def preview_cleaning(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: CleaningPreviewRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> CleaningPreviewResponse:
    """Run the pipeline in memory only. Nothing is written or persisted."""
    return await dataset_version_service.preview_cleaning(
        session,
        storage,
        current_user,
        project_id,
        dataset_id,
        payload.operations,
        payload.source_version_id,
    )


@router.post(
    "/clean",
    response_model=CleaningApplyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply a cleaning pipeline as a new version",
    responses=_RESPONSES,
)
async def apply_cleaning(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: CleaningApplyRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> CleaningApplyResponse:
    """Create a cleaned version. The original upload is never modified."""
    version, preview = await dataset_version_service.apply_cleaning(
        session, storage, current_user, project_id, dataset_id, payload
    )
    return CleaningApplyResponse(
        version=DatasetVersionResponse.model_validate(version),
        preview=preview,
    )


@router.get(
    "/versions",
    response_model=DatasetVersionListResponse,
    summary="List cleaned versions of a dataset",
    responses=_RESPONSES,
)
async def list_versions(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    pagination: PageParams,
) -> DatasetVersionListResponse:
    """Newest version first."""
    versions, total = await dataset_version_service.list_versions(
        session, current_user, project_id, dataset_id, pagination
    )
    return DatasetVersionListResponse.build(
        items=[DatasetVersionResponse.model_validate(v) for v in versions],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
