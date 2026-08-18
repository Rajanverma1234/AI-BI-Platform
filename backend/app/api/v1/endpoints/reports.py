"""Report endpoints, nested under a dataset.

Routes stay thin: they adapt HTTP to ``report_service`` and back. The download
route is the only one that does not return JSON - it returns the stored bytes
with a safe, server-generated filename. Storage keys are never exposed.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.pagination import PageParams
from app.core.rate_limit import HeavyRateLimit
from app.schemas.common import ErrorResponse
from app.schemas.report import (
    ReportData,
    ReportGenerateRequest,
    ReportListResponse,
    ReportOptionsResponse,
    ReportPreviewRequest,
    ReportResponse,
)
from app.services import report_service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}/reports",
    tags=["reports"],
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset, version or report not found"},
    422: {"model": ErrorResponse, "description": "The dataset cannot support this report"},
}

VersionQuery = Query(default=None, description="Report on a cleaned version instead.")


@router.get(
    "/options",
    response_model=ReportOptionsResponse,
    summary="Templates, sections and formats this dataset supports",
    responses=_RESPONSES,
)
async def report_options(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> ReportOptionsResponse:
    """Every section is returned, with a reason for any this dataset cannot fill."""
    return await report_service.options(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.post(
    "/preview",
    response_model=ReportData,
    summary="Build a report without exporting it",
    dependencies=[HeavyRateLimit],
    responses=_RESPONSES,
)
async def preview_report(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: ReportPreviewRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ReportData:
    """The exact object the PDF, XLSX, CSV and PPTX renderers receive."""
    return await report_service.preview(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and store a report",
    dependencies=[HeavyRateLimit],
    responses={
        **_RESPONSES,
        503: {"model": ErrorResponse, "description": "Storage unavailable"},
    },
)
async def generate_report(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: ReportGenerateRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ReportResponse:
    """Returns the report with its final status.

    A rendering failure comes back as a `failed` report rather than an error,
    so the attempt and its reason stay visible in the history.
    """
    report = await report_service.generate(
        session, storage, current_user, project_id, dataset_id, payload
    )
    return ReportResponse.model_validate(report)


@router.get(
    "",
    response_model=ReportListResponse,
    summary="List generated reports",
    responses=_RESPONSES,
)
async def list_reports(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    pagination: PageParams,
) -> ReportListResponse:
    """This user's reports for this dataset, newest first."""
    reports, total = await report_service.list_reports(
        session, storage, current_user, project_id, dataset_id, pagination
    )
    return ReportListResponse.build(
        items=[ReportResponse.model_validate(report) for report in reports],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Get one report's metadata",
    responses=_RESPONSES,
)
async def get_report(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    report_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ReportResponse:
    report = await report_service.get_report(
        session, storage, current_user, project_id, dataset_id, report_id
    )
    return ReportResponse.model_validate(report)


@router.get(
    "/{report_id}/download",
    summary="Download the rendered file",
    response_class=Response,
    responses={
        **_RESPONSES,
        200: {
            "description": "The rendered report",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        },
    },
)
async def download_report(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    report_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> Response:
    """The stored bytes, named from the report rather than from its storage key."""
    report, payload = await report_service.download(
        session, storage, current_user, project_id, dataset_id, report_id
    )
    filename = report_service.download_filename(report)
    return Response(
        content=payload,
        media_type=report_service.content_type(report.file_format),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Lets the browser read the name when the app fetches the blob.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a report and its stored file",
    responses=_RESPONSES,
)
async def delete_report(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    report_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> None:
    await report_service.delete_report(
        session, storage, current_user, project_id, dataset_id, report_id
    )
