"""Analytics orchestration: authorise, load once, compute, respond.

Every function goes through ``dataset_access.load_for_user``, which resolves
user -> workspace -> project -> dataset (and version) before any file is read,
so an id supplied by the client is never trusted.
"""

from __future__ import annotations

import uuid

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.user import User
from app.schemas.analytics import (
    AbcEnvelope,
    AbcRequest,
    AnalyticsMeta,
    ColumnRole,
    ComparisonSpec,
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
    KpiComparison,
    KpiDefinition,
    KpiFormat,
    KpiGroupValue,
    KpiResult,
    KpiSuggestion,
    MetricType,
    SegmentEnvelope,
    SegmentRequest,
    TimeSeriesEnvelope,
    TimeSeriesRequest,
    ValueFormat,
)
from app.services import analytics_engine, dataset_access
from app.services.dataset_query import apply_filters
from app.storage.base import StorageProvider

#: Column-name hints used to pick a sensible display format. Purely cosmetic -
#: the metric itself never depends on the column being named a certain way.
_MONEY_HINT = analytics_engine._MONEY_HINT


async def _load(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None,
) -> dataset_access.LoadedDataset:
    return await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )


def _meta(loaded: dataset_access.LoadedDataset, filtered: pd.DataFrame) -> AnalyticsMeta:
    return AnalyticsMeta(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        row_count=int(len(loaded.frame)),
        filtered_row_count=int(len(filtered)),
    )


# --- KPI catalogue -----------------------------------------------------------


def _format_for(column: str | None, metric: MetricType) -> KpiFormat:
    if metric in (MetricType.COUNT, MetricType.DISTINCT_COUNT):
        return KpiFormat(style=ValueFormat.INTEGER, decimals=0)
    if column and _MONEY_HINT.search(column):
        return KpiFormat(style=ValueFormat.CURRENCY, decimals=2)
    return KpiFormat(style=ValueFormat.NUMBER, decimals=2)


def build_catalog(frame: pd.DataFrame, loaded: dataset_access.LoadedDataset) -> KpiCatalogResponse:
    """Suggest only KPIs this dataset can actually support.

    Rule-based from detected column roles - nothing is assumed about the
    schema, and anything unsupported is reported with a reason instead of
    being shown as a fake value.
    """
    roles: list[ColumnRole] = analytics_engine.describe_columns(frame)
    # Measures, not "numeric": an id column is numeric but summing it is
    # meaningless, so identifiers are offered as distinct counts instead.
    measures = [role for role in roles if role.measure]
    categorical = [role for role in roles if role.categorical]
    temporal = [role for role in roles if role.temporal]
    identifiers = [role for role in roles if role.identifier]

    suggestions: list[KpiSuggestion] = [
        KpiSuggestion(
            definition=KpiDefinition(
                name="Total records",
                description="Number of rows in the dataset.",
                metric=MetricType.COUNT,
                format=KpiFormat(style=ValueFormat.INTEGER, decimals=0),
            ),
            reason="Always available: counts rows.",
        )
    ]

    for role in measures[:6]:
        suggestions.append(
            KpiSuggestion(
                definition=KpiDefinition(
                    name=f"Total {role.name}",
                    description=f"SUM of {role.name}.",
                    metric=MetricType.SUM,
                    column=role.name,
                    format=_format_for(role.name, MetricType.SUM),
                ),
                reason=f"'{role.name}' is numeric, so it can be summed.",
            )
        )
        suggestions.append(
            KpiSuggestion(
                definition=KpiDefinition(
                    name=f"Average {role.name}",
                    description=f"AVERAGE of {role.name}.",
                    metric=MetricType.AVERAGE,
                    column=role.name,
                    format=_format_for(role.name, MetricType.AVERAGE),
                ),
                reason=f"'{role.name}' is numeric, so it can be averaged.",
            )
        )

    for role in identifiers[:4]:
        suggestions.append(
            KpiSuggestion(
                definition=KpiDefinition(
                    name=f"Unique {role.name}",
                    description=f"DISTINCT COUNT of {role.name}.",
                    metric=MetricType.DISTINCT_COUNT,
                    column=role.name,
                    format=KpiFormat(style=ValueFormat.INTEGER, decimals=0),
                ),
                reason=(
                    f"'{role.name}' looks like an identifier, "
                    "so counting distinct values is meaningful."
                ),
            )
        )

    # A ratio needs a real measure and something to divide it by.
    if measures and identifiers:
        measure, entity = measures[0], identifiers[0]
        suggestions.append(
            KpiSuggestion(
                definition=KpiDefinition(
                    name=f"Average {measure.name} per {entity.name}",
                    description=f"SUM({measure.name}) / DISTINCT COUNT({entity.name}).",
                    formula={
                        "node": "binary",
                        "operator": "divide",
                        "left": {"node": "metric", "metric": "sum", "column": measure.name},
                        "right": {
                            "node": "metric",
                            "metric": "distinct_count",
                            "column": entity.name,
                        },
                    },
                    format=_format_for(measure.name, MetricType.AVERAGE),
                ),
                reason="A numeric measure divided by an identifier gives a per-entity value.",
            )
        )

    unavailable: list[dict[str, str]] = []
    if not measures:
        unavailable.append(
            {
                "kpi": "Value totals and averages",
                "reason": (
                    "This dataset has no measurable numeric columns. Identifier "
                    "columns are counted rather than summed."
                ),
            }
        )
    if not temporal:
        unavailable.append(
            {
                "kpi": "Growth and time-series KPIs",
                "reason": "This dataset has no recognisable date column.",
            }
        )
    if not identifiers:
        unavailable.append(
            {
                "kpi": "Entity counts (unique customers, orders, ...)",
                "reason": "No identifier-like column was detected.",
            }
        )
    if not categorical:
        unavailable.append(
            {
                "kpi": "Segmentation, contribution and ABC analysis",
                "reason": "This dataset has no categorical column to group by.",
            }
        )

    return KpiCatalogResponse(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        row_count=int(len(frame)),
        columns=roles,
        suggestions=suggestions,
        unavailable=unavailable,
    )


async def kpi_catalog(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> KpiCatalogResponse:
    loaded = await _load(session, storage, user, project_id, dataset_id, version_id)
    return build_catalog(loaded.frame, loaded)


# --- KPI evaluation ----------------------------------------------------------


def _comparison(
    frame: pd.DataFrame,
    definition: KpiDefinition,
    spec: ComparisonSpec,
    current_value: float | None,
) -> KpiComparison | None:
    """Compare the KPI against the previous period on the same time axis."""
    series = analytics_engine.build_time_series(
        frame,
        TimeSeriesRequest(
            date_column=spec.date_column,
            period=spec.period,
            metric=definition.metric or MetricType.COUNT,
            column=definition.column,
            filters=definition.filters,
        ),
    )
    points = series.series[0].points if series.series else []
    if len(points) < 2:
        return KpiComparison(period=spec.period)

    current, previous = points[-1], points[-2]
    absolute = None
    percentage = None
    if current.value is not None and previous.value is not None:
        absolute = current.value - previous.value
        # Growth against a zero base is undefined, not infinite.
        percentage = (
            None
            if previous.value == 0
            else ((current.value - previous.value) / previous.value) * 100
        )

    return KpiComparison(
        period=spec.period,
        current_label=current.label,
        previous_label=previous.label,
        previous_value=previous.value,
        absolute_change=absolute,
        percentage_change=percentage,
    )


def evaluate_kpi(frame: pd.DataFrame, definition: KpiDefinition) -> KpiResult:
    """Compute one KPI.

    A KPI that cannot be computed is returned as unavailable with a readable
    reason - never as a fabricated number.
    """
    result = KpiResult(
        name=definition.name,
        description=definition.description,
        metric=definition.metric,
        column=definition.column,
        format=definition.format,
    )

    try:
        scoped = apply_filters(frame, definition.filters) if definition.filters else frame

        if definition.formula is not None:
            result.value = analytics_engine.evaluate_formula(scoped, definition.formula)
        elif definition.metric is not None:
            result.value = analytics_engine.compute_metric(
                scoped, definition.metric, definition.column
            )
        else:
            result.available = False
            result.reason = "This KPI has neither a metric nor a formula."
            return result

        if definition.group_by:
            grouped = analytics_engine._grouped_metric(
                scoped,
                definition.group_by,
                definition.metric or MetricType.COUNT,
                definition.column,
            )
            result.groups = [
                KpiGroupValue(group=str(index), value=analytics_engine._safe(value))
                for index, value in grouped.sort_values(ascending=False).head(25).items()
            ]

        if result.value is None:
            result.available = False
            result.reason = (
                "The result is undefined for this data (no values, or a division by zero)."
            )

        if definition.comparison is not None:
            result.comparison = _comparison(
                scoped, definition, definition.comparison, result.value
            )

    except AppError as exc:
        # Expected failures (missing column, wrong type) explain themselves.
        result.available = False
        result.reason = exc.message

    return result


async def calculate_kpis(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: KpiCalculateRequest,
) -> KpiCalculateResponse:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    return KpiCalculateResponse(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        row_count=int(len(loaded.frame)),
        results=[evaluate_kpi(loaded.frame, definition) for definition in request.kpis],
    )


# --- Analyses ----------------------------------------------------------------


async def time_series(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: TimeSeriesRequest,
) -> TimeSeriesEnvelope:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    filtered = apply_filters(loaded.frame, request.filters)
    return TimeSeriesEnvelope(
        meta=_meta(loaded, filtered),
        result=analytics_engine.build_time_series(loaded.frame, request),
    )


async def growth(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: GrowthRequest,
) -> GrowthEnvelope:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    filtered = apply_filters(loaded.frame, request.filters)
    return GrowthEnvelope(
        meta=_meta(loaded, filtered),
        result=analytics_engine.build_growth(loaded.frame, request),
    )


async def segment(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: SegmentRequest,
) -> SegmentEnvelope:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    filtered = apply_filters(loaded.frame, request.filters)
    return SegmentEnvelope(
        meta=_meta(loaded, filtered),
        result=analytics_engine.build_segment(loaded.frame, request),
    )


async def contribution(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: SegmentRequest,
) -> ContributionEnvelope:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    filtered = apply_filters(loaded.frame, request.filters)
    return ContributionEnvelope(
        meta=_meta(loaded, filtered),
        result=analytics_engine.build_contribution(loaded.frame, request),
    )


async def abc_analysis(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: AbcRequest,
) -> AbcEnvelope:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    filtered = apply_filters(loaded.frame, request.filters)
    return AbcEnvelope(
        meta=_meta(loaded, filtered),
        result=analytics_engine.build_abc(loaded.frame, request),
    )


async def entity_analysis(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: EntityRequest,
) -> EntityEnvelope:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    filtered = apply_filters(loaded.frame, request.filters)
    return EntityEnvelope(
        meta=_meta(loaded, filtered),
        result=analytics_engine.build_entity_analysis(loaded.frame, request),
    )


async def distribution(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: DistributionRequest,
) -> DistributionEnvelope:
    loaded = await _load(session, storage, user, project_id, dataset_id, request.version_id)
    filtered = apply_filters(loaded.frame, request.filters)
    return DistributionEnvelope(
        meta=_meta(loaded, filtered),
        result=analytics_engine.build_distribution(loaded.frame, request),
    )
