"""AI insight endpoints.

Two routers. Dataset-scoped routes live under the usual project/dataset prefix
and authorise through ``dataset_access`` like every other analytics feature.
The run-scoped routes (``/insights/{run_id}``) carry no project in the path, so
they are scoped by owning user instead - a guessed id belonging to another
tenant is simply not found.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.pagination import PageParams
from app.core.rate_limit import AiRateLimit
from app.schemas.common import ErrorResponse
from app.schemas.insights import (
    GenerateInsightsRequest,
    InsightReport,
    InsightRunDetail,
    InsightRunListResponse,
    InsightRunResponse,
    RefreshInsightsRequest,
)
from app.services import insights_service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}/insights",
    tags=["insights"],
)
#: Routes addressed by run id alone, as described in the API design.
run_router = APIRouter(prefix="/insights", tags=["insights"])

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset, version or run not found"},
    422: {"model": ErrorResponse, "description": "The dataset cannot support this analysis"},
}

VersionQuery = Query(default=None, description="Analyse a cleaned version instead.")


@router.post(
    "",
    response_model=InsightReport,
    status_code=status.HTTP_201_CREATED,
    summary="Generate business insights and recommendations",
    dependencies=[AiRateLimit],
    responses=_RESPONSES,
)
async def generate_insights(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: GenerateInsightsRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> InsightReport:
    """Run the full pipeline and return the report.

    Deterministic insights are always produced; AI interpretation is additive
    and its absence is reported in `ai_status` rather than failing the request.
    """
    report, _run = await insights_service.generate(
        session, storage, current_user, project_id, dataset_id, payload
    )
    return report


@router.get(
    "",
    response_model=InsightRunListResponse,
    summary="List previous insight runs",
    responses=_RESPONSES,
)
async def list_insight_runs(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    pagination: PageParams,
) -> InsightRunListResponse:
    """This user's runs for this dataset, newest first."""
    runs, total = await insights_service.list_runs(
        session, storage, current_user, project_id, dataset_id, pagination
    )
    return InsightRunListResponse.build(
        items=[InsightRunResponse.model_validate(run) for run in runs],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/latest",
    response_model=InsightRunDetail | None,
    summary="The most recent insight run for this dataset",
    responses=_RESPONSES,
)
async def latest_insight_run(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> InsightRunDetail | None:
    """Null when nothing has been generated yet.

    The report is flagged `stale` when it was produced for a different version
    or by older detection rules, so an old run is never shown as current.
    """
    run = await insights_service.latest_run(
        session, storage, current_user, project_id, dataset_id, version_id
    )
    if run is None:
        return None
    return InsightRunDetail(
        run=InsightRunResponse.model_validate(run),
        report=insights_service.stored_report(
            run, viewing_version=version_id, compare_version=True
        ),
    )


@run_router.get(
    "/{run_id}",
    response_model=InsightRunDetail,
    summary="Get a stored insight run",
    responses=_RESPONSES,
)
async def get_insight_run(
    run_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> InsightRunDetail:
    run = await insights_service.get_run(session, current_user, run_id)
    return InsightRunDetail(
        run=InsightRunResponse.model_validate(run),
        report=insights_service.stored_report(run),
    )


@run_router.post(
    "/{run_id}/refresh",
    response_model=InsightRunDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Re-run the analysis for a stored run's dataset and version",
    dependencies=[AiRateLimit],
    responses=_RESPONSES,
)
async def refresh_insight_run(
    run_id: uuid.UUID,
    payload: RefreshInsightsRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> InsightRunDetail:
    """Records a new run rather than overwriting the old one."""
    report, run = await insights_service.refresh(
        session, storage, current_user, run_id, payload.include_ai
    )
    return InsightRunDetail(run=InsightRunResponse.model_validate(run), report=report)
