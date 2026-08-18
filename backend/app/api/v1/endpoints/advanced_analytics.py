"""Advanced analytics endpoints.

Mounted under the existing analytics prefix rather than a parallel one, and
only for analyses that did not already have a route: ABC (`/abc-analysis`),
correlation (`/correlation`) and statistics (`/eda`, `/distribution`) already
exist and are reused by the frontend as-is.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, Storage
from app.core.rate_limit import HeavyRateLimit
from app.schemas.advanced_analytics import (
    AdvancedCapabilities,
    ChurnRequest,
    ChurnResponse,
    CohortRequest,
    CohortResponse,
    ForecastRequest,
    ForecastResponse,
    OutlierRequest,
    OutlierResponse,
    ParetoRequest,
    ParetoResponse,
    RfmRequest,
    RfmResponse,
    SegmentationRequest,
    SegmentationResponse,
)
from app.schemas.common import ErrorResponse
from app.services import advanced_analytics_service as service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}/analytics",
    tags=["advanced-analytics"],
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset or version not accessible"},
    422: {"model": ErrorResponse, "description": "Missing columns or insufficient data"},
}

VersionQuery = Query(default=None, description="Analyse a cleaned version instead.")


@router.get(
    "/capabilities",
    response_model=AdvancedCapabilities,
    summary="Which advanced analyses this dataset supports",
    responses=_RESPONSES,
)
async def capabilities(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> AdvancedCapabilities:
    """Detected columns plus the reason any analysis is unavailable."""
    return await service.capabilities(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.post("/rfm", response_model=RfmResponse, summary="RFM analysis", responses=_RESPONSES)
async def rfm(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: RfmRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> RfmResponse:
    """Recency, frequency and monetary scoring with standard segments."""
    return await service.rfm(session, storage, current_user, project_id, dataset_id, payload)


@router.post(
    "/segmentation",
    response_model=SegmentationResponse,
    summary="K-Means customer/entity segmentation",
    dependencies=[HeavyRateLimit],
    responses=_RESPONSES,
)
async def segmentation(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: SegmentationRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> SegmentationResponse:
    """Deterministic K-Means with a PCA projection for plotting."""
    return await service.segmentation(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/cohort", response_model=CohortResponse, summary="Cohort retention", responses=_RESPONSES
)
async def cohort(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: CohortRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> CohortResponse:
    return await service.cohort(session, storage, current_user, project_id, dataset_id, payload)


@router.post(
    "/churn", response_model=ChurnResponse, summary="Rule-based churn", responses=_RESPONSES
)
async def churn(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: ChurnRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ChurnResponse:
    """Inactivity-threshold classification. No model is trained."""
    return await service.churn(session, storage, current_user, project_id, dataset_id, payload)


@router.post(
    "/forecast",
    response_model=ForecastResponse,
    summary="Time-series forecast",
    dependencies=[HeavyRateLimit],
    responses=_RESPONSES,
)
async def forecast(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: ForecastRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ForecastResponse:
    """Exponential smoothing with residual-based prediction intervals."""
    return await service.forecast(session, storage, current_user, project_id, dataset_id, payload)


@router.post(
    "/outliers", response_model=OutlierResponse, summary="Outlier detection", responses=_RESPONSES
)
async def outliers(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: OutlierRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> OutlierResponse:
    """Identifies and explains outliers; never removes them."""
    return await service.outliers(session, storage, current_user, project_id, dataset_id, payload)


@router.post(
    "/pareto", response_model=ParetoResponse, summary="Pareto analysis", responses=_RESPONSES
)
async def pareto(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: ParetoRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> ParetoResponse:
    return await service.pareto(session, storage, current_user, project_id, dataset_id, payload)
