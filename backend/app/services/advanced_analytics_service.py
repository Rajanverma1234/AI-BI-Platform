"""Advanced analytics orchestration.

Authorises and loads once through ``dataset_access``, resolves which column
plays each role (detection + user override), then calls the engine. Column
detection reuses ``semantic_columns``; ABC, correlation and statistics reuse
the existing analytics services rather than being reimplemented.
"""

from __future__ import annotations

import uuid

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.user import User
from app.schemas.advanced_analytics import (
    AdvancedCapabilities,
    AnalysisMeta,
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
    RequirementError,
    RfmRequest,
    RfmResponse,
    SegmentationRequest,
    SegmentationResponse,
)
from app.schemas.analytics import SegmentRequest, TimeSeriesRequest
from app.schemas.cleaning import OutlierMethod
from app.services import (
    advanced_analytics_engine as engine,
)
from app.services import (
    analytics_engine,
    dataset_access,
    dataset_cleaning,
    semantic_columns,
)
from app.services.dataset_query import apply_filters
from app.storage.base import StorageProvider

#: Roles each analysis needs, used for both capability reporting and errors.
REQUIREMENTS: dict[str, list[str]] = {
    "rfm": ["customer", "date", "revenue"],
    "cohort": ["customer", "date"],
    "churn": ["customer", "date"],
    "forecast": ["date", "revenue"],
    "segmentation": ["measure"],
    "abc": ["dimension", "revenue"],
    "pareto": ["dimension", "revenue"],
    "correlation": ["measure"],
    "outliers": ["measure"],
    "statistics": ["measure"],
}

ROLE_LABELS = {
    "customer": "a customer/entity identifier",
    "date": "a transaction or activity date",
    "revenue": "a monetary/revenue field",
    "dimension": "a categorical dimension",
    "measure": "at least one numeric measure",
}


async def _load(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None,
) -> tuple[dataset_access.LoadedDataset, semantic_columns.SemanticModel]:
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    if loaded.frame.empty:
        raise ValidationError("This dataset has no rows to analyse.")
    return loaded, semantic_columns.detect(loaded.frame)


def _resolve(
    frame: pd.DataFrame,
    model: semantic_columns.SemanticModel,
    role: str,
    override: str | None,
    analysis: str,
) -> str:
    """User override wins; otherwise fall back to detection. Never assumed."""
    if override:
        if override not in frame.columns:
            raise ValidationError(f"The dataset has no column called '{override}'.")
        return override

    detected = model.get(role)
    if detected is None:
        raise ValidationError(
            f"{analysis} requires {ROLE_LABELS.get(role, role)}. None was detected in "
            "this dataset - select the column manually."
        )
    return detected


def _meta(
    loaded: dataset_access.LoadedDataset,
    frame: pd.DataFrame,
    columns_used: dict[str, str],
    warnings: list[str] | None = None,
) -> AnalysisMeta:
    return AnalysisMeta(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        row_count=int(len(frame)),
        columns_used=columns_used,
        warnings=warnings or [],
    )


# --- Capabilities ------------------------------------------------------------


def present_roles(model: semantic_columns.SemanticModel) -> dict[str, str | None]:
    """Which business roles this dataset actually offers.

    Pure and reusable: reporting asks the same question about an
    already-loaded frame, so the rules live here rather than being restated.
    """
    return {
        "customer": model.get("customer")
        or (model.identifiers[0].name if model.identifiers else None),
        "date": model.get("date"),
        "revenue": model.get("revenue"),
        "dimension": model.dimensions[0].name if model.dimensions else None,
        "measure": model.measures[0].name if model.measures else None,
    }


def describe_requirement(analysis: str, roles: list[str]) -> str:
    """The user-facing sentence explaining what an analysis needs."""
    return (
        f"{analysis.replace('_', ' ').title()} requires "
        + " and ".join(ROLE_LABELS.get(role, role) for role in roles)
        + "."
    )


async def capabilities(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> AdvancedCapabilities:
    """Which analyses this dataset supports, with reasons for those it does not."""
    loaded, model = await _load(session, storage, user, project_id, dataset_id, version_id)

    present = present_roles(model)
    detected = {role: column for role, column in present.items() if column}

    available: list[str] = []
    unavailable: list[RequirementError] = []

    for analysis, roles in REQUIREMENTS.items():
        missing = [role for role in roles if not present.get(role)]
        if missing:
            unavailable.append(
                RequirementError(
                    analysis=analysis,
                    message=describe_requirement(analysis, roles),
                    required_roles=roles,
                    missing_roles=missing,
                )
            )
        else:
            available.append(analysis)

    return AdvancedCapabilities(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        detected_columns=detected,
        available=available,
        unavailable=unavailable,
    )


# --- Analyses ----------------------------------------------------------------


async def rfm(
    session: AsyncSession, storage: StorageProvider, user: User,
    project_id: uuid.UUID, dataset_id: uuid.UUID, request: RfmRequest,
) -> RfmResponse:
    loaded, model = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    frame = apply_filters(loaded.frame, request.filters)

    customer = _resolve(frame, model, "customer", request.customer_column, "RFM analysis")
    date = _resolve(frame, model, "date", request.date_column, "RFM analysis")
    monetary = _resolve(frame, model, "revenue", request.monetary_column, "RFM analysis")

    segments, customers, context = engine.build_rfm(frame, customer, date, monetary)

    if request.segment:
        customers = [item for item in customers if item.segment is request.segment]

    return RfmResponse(
        meta=_meta(loaded, frame, {"customer": customer, "date": date, "monetary": monetary}),
        reference_date=context["reference_date"],
        customer_count=context["customer_count"],
        total_monetary=context["total_monetary"],
        segments=segments,
        customers=customers[: request.limit],
        score_distribution=context["score_distribution"],
    )


async def segmentation(
    session: AsyncSession, storage: StorageProvider, user: User,
    project_id: uuid.UUID, dataset_id: uuid.UUID, request: SegmentationRequest,
) -> SegmentationResponse:
    loaded, model = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    frame = apply_filters(loaded.frame, request.filters)

    features = request.feature_columns or [column.name for column in model.measures][:5]
    if len(features) < 2:
        raise ValidationError(
            "Clustering needs at least two numeric measures. Select the features manually."
        )
    for column in features:
        if column not in frame.columns:
            raise ValidationError(f"The dataset has no column called '{column}'.")

    entity = request.entity_column
    if entity and entity not in frame.columns:
        raise ValidationError(f"The dataset has no column called '{entity}'.")

    profiles, points, context = engine.build_segmentation(
        frame, features, request.clusters, request.standardize, entity, request.limit
    )

    warnings = []
    if context["explained_variance"] < 0.5:
        warnings.append(
            f"The two plotted components capture only "
            f"{context['explained_variance'] * 100:.0f}% of the variance, so the scatter "
            "is an approximation of the clustering."
        )

    return SegmentationResponse(
        meta=_meta(loaded, frame, {"features": ", ".join(context["features"])}, warnings),
        features=context["features"],
        clusters=request.clusters,
        standardized=request.standardize,
        explained_variance=context["explained_variance"],
        iterations=context["iterations"],
        profiles=profiles,
        points=points,
    )


async def cohort(
    session: AsyncSession, storage: StorageProvider, user: User,
    project_id: uuid.UUID, dataset_id: uuid.UUID, request: CohortRequest,
) -> CohortResponse:
    loaded, model = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    frame = apply_filters(loaded.frame, request.filters)

    customer = _resolve(frame, model, "customer", request.customer_column, "Cohort analysis")
    date = _resolve(frame, model, "date", request.date_column, "Cohort analysis")

    rows, labels, averages = engine.build_cohort(
        frame, customer, date, request.period, request.max_periods
    )

    return CohortResponse(
        meta=_meta(loaded, frame, {"customer": customer, "date": date}),
        period=request.period,
        period_labels=labels,
        rows=rows,
        average_retention=averages,
    )


async def churn(
    session: AsyncSession, storage: StorageProvider, user: User,
    project_id: uuid.UUID, dataset_id: uuid.UUID, request: ChurnRequest,
) -> ChurnResponse:
    loaded, model = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    frame = apply_filters(loaded.frame, request.filters)

    customer = _resolve(frame, model, "customer", request.customer_column, "Churn analysis")
    date = _resolve(frame, model, "date", request.date_column, "Churn analysis")
    monetary = request.monetary_column or model.get("revenue")
    if monetary and monetary not in frame.columns:
        raise ValidationError(f"The dataset has no column called '{monetary}'.")

    result = engine.build_churn(
        frame, customer, date, monetary, request.churn_days, request.at_risk_days, request.limit
    )

    used = {"customer": customer, "date": date}
    if monetary:
        used["monetary"] = monetary

    return ChurnResponse(
        meta=_meta(loaded, frame, used),
        method_note=(
            "Rule-based: customers are classified by days since their last recorded "
            "activity. No predictive model is trained and nothing is forecast."
        ),
        churn_days=request.churn_days,
        at_risk_days=request.at_risk_days,
        **result,
    )


async def forecast(
    session: AsyncSession, storage: StorageProvider, user: User,
    project_id: uuid.UUID, dataset_id: uuid.UUID, request: ForecastRequest,
) -> ForecastResponse:
    loaded, model = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    frame = apply_filters(loaded.frame, request.filters)

    date = _resolve(frame, model, "date", request.date_column, "Forecasting")
    metric_column = request.metric_column or model.get("revenue")
    if metric_column and metric_column not in frame.columns:
        raise ValidationError(f"The dataset has no column called '{metric_column}'.")

    # Reuse the existing time-series builder rather than re-aggregating.
    series = analytics_engine.build_time_series(
        frame,
        TimeSeriesRequest(
            date_column=date,
            period=request.period,
            metric=request.metric,
            column=metric_column,
            max_points=500,
        ),
    )
    raw_points = series.series[0].points if series.series else []
    points = [point for point in raw_points if point.value is not None]

    history, projection, context = engine.build_forecast(
        [point.label for point in points],
        [float(point.value or 0) for point in points],
        request.method,
        request.horizon,
        request.period,
    )

    return ForecastResponse(
        meta=_meta(loaded, frame, {"date": date, "metric": metric_column or "count"}),
        method=request.method,
        period=request.period,
        horizon=request.horizon,
        periods_observed=context["periods_observed"],
        trend=context["trend"],
        mean_absolute_error=context["mean_absolute_error"],
        history=history,
        forecast=projection,
    )


async def outliers(
    session: AsyncSession, storage: StorageProvider, user: User,
    project_id: uuid.UUID, dataset_id: uuid.UUID, request: OutlierRequest,
) -> OutlierResponse:
    """Identify only - this module never removes anything."""
    loaded, _ = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    frame = apply_filters(loaded.frame, request.filters)

    if request.column not in frame.columns:
        raise ValidationError(f"The dataset has no column called '{request.column}'.")

    values = pd.to_numeric(frame[request.column], errors="coerce").dropna()
    if values.empty:
        raise ValidationError(f"Column '{request.column}' has no numeric values.")

    method = OutlierMethod.IQR if request.method == "iqr" else OutlierMethod.ZSCORE
    mask = dataset_cleaning.outlier_mask(values, method, request.threshold)
    flagged = values[mask]

    q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
    if method is OutlierMethod.IQR:
        iqr = q3 - q1
        lower, upper = q1 - request.threshold * iqr, q3 + request.threshold * iqr
    else:
        mean, std = float(values.mean()), float(values.std())
        lower, upper = mean - request.threshold * std, mean + request.threshold * std

    return OutlierResponse(
        meta=_meta(loaded, frame, {"column": request.column}),
        column=request.column,
        method=request.method,
        threshold=request.threshold,
        total_observations=int(len(values)),
        outlier_count=int(len(flagged)),
        outlier_percentage=round((len(flagged) / len(values)) * 100, 2) if len(values) else 0.0,
        lower_bound=round(lower, 4),
        upper_bound=round(upper, 4),
        minimum=round(float(values.min()), 4),
        q1=round(q1, 4),
        median=round(float(values.median()), 4),
        q3=round(q3, 4),
        maximum=round(float(values.max()), 4),
        outliers=[
            {"row": int(index), "value": round(float(value), 4)}
            for index, value in flagged.head(request.limit).items()
        ],
    )


async def pareto(
    session: AsyncSession, storage: StorageProvider, user: User,
    project_id: uuid.UUID, dataset_id: uuid.UUID, request: ParetoRequest,
) -> ParetoResponse:
    """Built on the existing contribution engine; no new aggregation logic."""
    loaded, _ = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    frame = apply_filters(loaded.frame, request.filters)

    contribution = analytics_engine.build_contribution(
        frame,
        SegmentRequest(
            dimension=request.dimension,
            metric=request.metric,
            column=request.column,
            limit=request.limit,
        ),
    )

    rows, vital_few = engine.pareto_from_contribution(contribution, request.threshold)

    return ParetoResponse(
        meta=_meta(loaded, frame, {"dimension": request.dimension}),
        dimension=request.dimension,
        metric=request.metric,
        column=request.column,
        total=round(contribution.total or 0.0, 4),
        threshold=request.threshold,
        vital_few_count=vital_few,
        vital_few_percentage_of_items=(
            round((vital_few / contribution.group_count) * 100, 2)
            if contribution.group_count
            else 0.0
        ),
        rows=rows,
    )
