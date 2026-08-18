"""KPI and business-analytics endpoints for a dataset.

Routes stay thin: authorization runs through the shared dependency and
``dataset_access``; all computation lives in the analytics engine.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, Storage
from app.schemas.analytics import (
    AbcEnvelope,
    AbcRequest,
    ContributionEnvelope,
    DistributionEnvelope,
    DistributionRequest,
    EntityEnvelope,
    EntityRequest,
    GrowthEnvelope,
    GrowthRequest,
    KpiCalculateRequest,
    KpiCalculateResponse,
    KpiCatalogResponse,
    RankingRequest,
    SegmentEnvelope,
    SegmentRequest,
    TimeSeriesEnvelope,
    TimeSeriesRequest,
)
from app.schemas.common import ErrorResponse
from app.services import analytics_service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}/analytics",
    tags=["dataset-analytics"],
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset or version not accessible"},
    422: {"model": ErrorResponse, "description": "Invalid column, metric, filter or formula"},
}

VersionQuery = Query(
    default=None,
    description="Analyse a cleaned version instead of the original upload.",
)


@router.get(
    "/kpis",
    response_model=KpiCatalogResponse,
    summary="KPIs this dataset can support",
    responses=_RESPONSES,
)
async def list_kpis(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> KpiCatalogResponse:
    """Column roles plus rule-based KPI suggestions.

    Anything that cannot be computed is listed under `unavailable` with a
    reason rather than offered as a KPI that would return a fake value.
    """
    return await analytics_service.kpi_catalog(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.post(
    "/kpis/calculate",
    response_model=KpiCalculateResponse,
    summary="Calculate KPI definitions",
    responses=_RESPONSES,
)
async def calculate_kpis(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: KpiCalculateRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> KpiCalculateResponse:
    """Each KPI resolves independently; one failure does not fail the batch."""
    return await analytics_service.calculate_kpis(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/time-series",
    response_model=TimeSeriesEnvelope,
    summary="Metric over a time axis",
    responses=_RESPONSES,
)
async def time_series(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: TimeSeriesRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> TimeSeriesEnvelope:
    return await analytics_service.time_series(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/growth",
    response_model=GrowthEnvelope,
    summary="Period-over-period growth",
    responses=_RESPONSES,
)
async def growth(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: GrowthRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> GrowthEnvelope:
    """Insufficient history is reported in `message`, not raised as an error."""
    return await analytics_service.growth(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/segment",
    response_model=SegmentEnvelope,
    summary="Metric broken down by a dimension",
    responses=_RESPONSES,
)
async def segment(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: SegmentRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> SegmentEnvelope:
    return await analytics_service.segment(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/ranking",
    response_model=SegmentEnvelope,
    summary="Top-N / bottom-N by a metric",
    responses=_RESPONSES,
)
async def ranking(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: RankingRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> SegmentEnvelope:
    """Same shape as `/segment`; `sort` selects the top or bottom end."""
    return await analytics_service.segment(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/contribution",
    response_model=ContributionEnvelope,
    summary="Contribution share per group",
    responses=_RESPONSES,
)
async def contribution(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: SegmentRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ContributionEnvelope:
    return await analytics_service.contribution(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/abc-analysis",
    response_model=AbcEnvelope,
    summary="ABC classification by cumulative contribution",
    responses=_RESPONSES,
)
async def abc_analysis(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: AbcRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> AbcEnvelope:
    """Thresholds default to 80/95 but are configurable per request."""
    return await analytics_service.abc_analysis(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/entity-analysis",
    response_model=EntityEnvelope,
    summary="Per-identifier behaviour",
    responses=_RESPONSES,
)
async def entity_analysis(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: EntityRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> EntityEnvelope:
    """The identifier column is always chosen by the caller."""
    return await analytics_service.entity_analysis(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/distribution",
    response_model=DistributionEnvelope,
    summary="Descriptive statistics and histogram buckets",
    responses=_RESPONSES,
)
async def distribution(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DistributionRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> DistributionEnvelope:
    """Buckets are returned as data; the existing chart components render them."""
    return await analytics_service.distribution(
        session, storage, current_user, project_id, dataset_id, payload
    )
