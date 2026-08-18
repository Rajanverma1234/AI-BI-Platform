"""Preview, query, chart and EDA endpoints for a dataset.

Authorization runs through the shared dependency and ``dataset_access``, which
resolves user -> workspace -> project -> dataset before any file is read. No
column name, filter or aggregation from the client is trusted: each is
validated against the loaded frame in the service layer.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, Storage
from app.core.pagination import Pagination
from app.schemas.common import ErrorResponse
from app.schemas.visualization import (
    DEFAULT_PREVIEW_ROWS,
    MAX_PREVIEW_ROWS,
    ChartConfig,
    ChartDataResponse,
    ChartSuggestionsResponse,
    CorrelationResponse,
    DataPreviewResponse,
    EdaSummaryResponse,
    QueryRequest,
    QueryResponse,
)
from app.services import visualization_service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}",
    tags=["dataset-visualization"],
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset or version not accessible"},
    422: {"model": ErrorResponse, "description": "Invalid column, filter or chart configuration"},
}

VersionQuery = Query(
    default=None,
    description="Use a cleaned version instead of the original upload.",
)


@router.get(
    "/preview",
    response_model=DataPreviewResponse,
    summary="Preview dataset rows",
    responses=_RESPONSES,
)
async def preview_rows(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PREVIEW_ROWS, ge=1, le=MAX_PREVIEW_ROWS),
    version_id: uuid.UUID | None = VersionQuery,
) -> DataPreviewResponse:
    """One bounded page of rows; the full dataset is never sent to the client."""
    return await visualization_service.preview(
        session,
        storage,
        current_user,
        project_id,
        dataset_id,
        Pagination(page=page, page_size=page_size),
        version_id,
    )


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Filter and aggregate a dataset",
    responses=_RESPONSES,
)
async def run_query(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: QueryRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> QueryResponse:
    """Structured filters and aggregations, evaluated server-side."""
    return await visualization_service.run_query(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/chart",
    response_model=ChartDataResponse,
    summary="Build chart data from a chart configuration",
    responses=_RESPONSES,
)
async def build_chart(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    config: ChartConfig,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ChartDataResponse:
    """Returns data only - colours and layout are the frontend's concern."""
    return await visualization_service.build_chart(
        session, storage, current_user, project_id, dataset_id, config
    )


@router.get(
    "/eda",
    response_model=EdaSummaryResponse,
    summary="Exploratory summary per column type",
    responses=_RESPONSES,
)
async def eda_summary(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> EdaSummaryResponse:
    return await visualization_service.eda_summary(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.get(
    "/correlation",
    response_model=CorrelationResponse,
    summary="Pairwise correlation across numeric columns",
    responses=_RESPONSES,
)
async def correlation(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> CorrelationResponse:
    """Constant and near-empty columns are reported as excluded, not errors."""
    return await visualization_service.correlation(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.get(
    "/chart-suggestions",
    response_model=ChartSuggestionsResponse,
    summary="Rule-based chart suggestions",
    responses=_RESPONSES,
)
async def chart_suggestions(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> ChartSuggestionsResponse:
    """Derived from detected column types with a fixed decision table."""
    return await visualization_service.chart_suggestions(
        session, storage, current_user, project_id, dataset_id, version_id
    )
