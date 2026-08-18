"""Deterministic KPI and business-analytics computation.

Pure functions over a DataFrame: no database, no HTTP, no LLM. Filtering is
reused from ``dataset_query`` rather than reimplemented.

Every metric is null-safe. Undefined results (empty selection, division by
zero, non-numeric column) come back as ``None`` with a reason rather than
raising, so a dashboard can show "not available" instead of failing outright.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.schemas.analytics import (
    NUMERIC_METRICS,
    AbcClassSummary,
    AbcRequest,
    AbcResponse,
    AbcRow,
    BinaryNode,
    BinaryOperator,
    ColumnRole,
    ConstantNode,
    ContributionResponse,
    ContributionRow,
    DistributionBucket,
    DistributionRequest,
    DistributionResponse,
    EntityRequest,
    EntityResponse,
    EntityRow,
    GrowthPoint,
    GrowthRequest,
    GrowthResponse,
    MetricRef,
    MetricType,
    SegmentRequest,
    SegmentResponse,
    SegmentRow,
    SortDirection,
    TimePeriod,
    TimeSeriesPoint,
    TimeSeriesRequest,
    TimeSeriesResponse,
    TimeSeriesSeries,
)
from app.schemas.profiling import DetectedType
from app.services.dataset_profiling import detect_type
from app.services.dataset_query import NUMERIC_TYPES, apply_filters, require_column

#: Pandas offset aliases for each supported period.
PERIOD_FREQ: dict[TimePeriod, str] = {
    TimePeriod.DAY: "D",
    TimePeriod.WEEK: "W",
    TimePeriod.MONTH: "MS",
    TimePeriod.QUARTER: "QS",
    TimePeriod.YEAR: "YS",
}

PERIOD_LABEL_FORMAT: dict[TimePeriod, str] = {
    TimePeriod.DAY: "%Y-%m-%d",
    TimePeriod.WEEK: "%Y-W%V",
    TimePeriod.MONTH: "%Y-%m",
    TimePeriod.QUARTER: "%Y-%m",
    TimePeriod.YEAR: "%Y",
}

#: Column-name hints used only to *suggest* KPIs; never to assume a schema.
_MONEY_HINT = re.compile(r"(revenue|sales|amount|price|cost|profit|value|total)", re.I)
_ID_HINT = re.compile(r"(_id$|^id$|code|number|no\.?$|uuid|key)", re.I)

#: A categorical column with more distinct values than this is treated as an
#: identifier rather than a grouping dimension.
MAX_DIMENSION_CARDINALITY = 1000
#: An integer column at least this unique per row is treated as a key.
NEAR_UNIQUE_RATIO = 0.95
#: Percentile set reported by distribution analysis.
PERCENTILES = (0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def _safe(value: Any) -> float | None:
    """Coerce to a JSON-safe float; NaN/Inf/non-numeric become None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _label(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "(empty)"
    return str(value)


# --- Metrics -----------------------------------------------------------------


def compute_metric(
    frame: pd.DataFrame,
    metric: MetricType,
    column: str | None,
) -> float | None:
    """Apply one aggregation. Returns None when undefined for this data."""
    if metric is MetricType.COUNT and column is None:
        return float(len(frame))

    if column is None:
        raise ValidationError(f"Metric '{metric.value}' requires a column.")

    require_column(frame, column)
    series = frame[column]

    if metric is MetricType.COUNT:
        return float(series.count())
    if metric is MetricType.DISTINCT_COUNT:
        return float(series.nunique(dropna=True))

    detected = detect_type(series)
    if metric in NUMERIC_METRICS and detected not in NUMERIC_TYPES:
        raise ValidationError(
            f"'{metric.value}' needs a numeric column, but '{column}' is {detected.value}."
        )

    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None

    match metric:
        case MetricType.SUM:
            return _safe(values.sum())
        case MetricType.AVERAGE:
            return _safe(values.mean())
        case MetricType.MEDIAN:
            return _safe(values.median())
        case MetricType.MIN:
            return _safe(values.min())
        case MetricType.MAX:
            return _safe(values.max())
        case MetricType.RANGE:
            return _safe(values.max() - values.min())
        case MetricType.STD_DEV:
            # Undefined for a single observation.
            return _safe(values.std()) if len(values) > 1 else None

    return None


# --- Formula engine ----------------------------------------------------------


def evaluate_formula(frame: pd.DataFrame, node: Any, depth: int = 0) -> float | None:
    """Evaluate the restricted expression tree.

    There is no string parsing and no eval: only metric references, numeric
    constants and the four arithmetic operators can be expressed. Division by
    zero yields None rather than raising.
    """
    if depth > 8:
        raise ValidationError("Formula is nested too deeply.")

    if isinstance(node, ConstantNode):
        return _safe(node.value)

    if isinstance(node, MetricRef):
        scoped = apply_filters(frame, node.filters) if node.filters else frame
        return compute_metric(scoped, node.metric, node.column)

    if isinstance(node, BinaryNode):
        left = evaluate_formula(frame, node.left, depth + 1)
        right = evaluate_formula(frame, node.right, depth + 1)

        # Any undefined operand makes the whole expression undefined.
        if left is None or right is None:
            return None

        match node.operator:
            case BinaryOperator.ADD:
                return _safe(left + right)
            case BinaryOperator.SUBTRACT:
                return _safe(left - right)
            case BinaryOperator.MULTIPLY:
                return _safe(left * right)
            case BinaryOperator.DIVIDE:
                # Division by zero is a data condition, not an error.
                return None if right == 0 else _safe(left / right)

    raise ValidationError("Unsupported formula node.")


# --- Time helpers ------------------------------------------------------------


def parse_dates(frame: pd.DataFrame, date_column: str) -> pd.Series:
    """Parse a column as dates, rejecting columns that are not date-like."""
    require_column(frame, date_column)
    series = frame[date_column]

    if not pd.api.types.is_datetime64_any_dtype(series):
        if detect_type(series) is not DetectedType.DATETIME:
            raise ValidationError(
                f"Column '{date_column}' does not contain recognisable dates."
            )
        series = pd.to_datetime(series, errors="coerce", format="mixed")

    if series.dropna().empty:
        raise ValidationError(f"Column '{date_column}' has no valid dates.")
    return series


def _period_labels(index: pd.DatetimeIndex, period: TimePeriod) -> list[str]:
    if period is TimePeriod.QUARTER:
        return [f"{ts.year}-Q{ts.quarter}" for ts in index]
    return [ts.strftime(PERIOD_LABEL_FORMAT[period]) for ts in index]


def build_time_series(frame: pd.DataFrame, request: TimeSeriesRequest) -> TimeSeriesResponse:
    """Resample a metric onto a time axis."""
    working = apply_filters(frame, request.filters)
    dates = parse_dates(working, request.date_column)

    working = working.assign(_period=dates)
    working = working.dropna(subset=["_period"])
    if working.empty:
        return TimeSeriesResponse(
            date_column=request.date_column,
            period=request.period,
            metric=request.metric,
            column=request.column,
        )

    grouper = pd.Grouper(key="_period", freq=PERIOD_FREQ[request.period])

    if request.group_by:
        dimension = require_column(working, request.group_by)
        buckets = working.groupby([grouper, dimension], dropna=False)
    else:
        buckets = working.groupby(grouper)

    reduced = buckets.apply(
        lambda chunk: compute_metric(chunk, request.metric, request.column),
        include_groups=False,
    )

    if request.group_by:
        pivot = reduced.unstack(fill_value=None)
        index = pivot.index
        truncated = len(index) > request.max_points
        if truncated:
            pivot = pivot.tail(request.max_points)
            index = pivot.index
        labels = _period_labels(pd.DatetimeIndex(index), request.period)
        series = [
            TimeSeriesSeries(
                name=_label(name),
                points=[
                    TimeSeriesPoint(label=label, value=_safe(value))
                    for label, value in zip(labels, pivot[name].tolist(), strict=False)
                ],
            )
            for name in pivot.columns
        ]
    else:
        truncated = len(reduced) > request.max_points
        if truncated:
            reduced = reduced.tail(request.max_points)
        labels = _period_labels(pd.DatetimeIndex(reduced.index), request.period)
        series = [
            TimeSeriesSeries(
                name=request.column or request.metric.value,
                points=[
                    TimeSeriesPoint(label=label, value=_safe(value))
                    for label, value in zip(labels, reduced.tolist(), strict=False)
                ],
            )
        ]

    return TimeSeriesResponse(
        date_column=request.date_column,
        period=request.period,
        metric=request.metric,
        column=request.column,
        labels=labels,
        series=series,
        truncated=truncated,
    )


def _growth_points(labels: list[str], values: list[float | None]) -> list[GrowthPoint]:
    points: list[GrowthPoint] = []
    previous: float | None = None

    for label, value in zip(labels, values, strict=False):
        absolute: float | None = None
        percentage: float | None = None

        if value is not None and previous is not None:
            absolute = _safe(value - previous)
            # Growth against a zero base is undefined, not infinite.
            percentage = None if previous == 0 else _safe(((value - previous) / previous) * 100)

        points.append(
            GrowthPoint(
                label=label,
                value=value,
                previous_value=previous,
                absolute_change=absolute,
                percentage_change=percentage,
            )
        )
        previous = value

    return points


def build_growth(frame: pd.DataFrame, request: GrowthRequest) -> GrowthResponse:
    """Period-over-period change across the whole time axis."""
    series = build_time_series(
        frame,
        TimeSeriesRequest(
            version_id=request.version_id,
            date_column=request.date_column,
            period=request.period,
            metric=request.metric,
            column=request.column,
            filters=request.filters,
        ),
    )

    values = [point.value for point in series.series[0].points] if series.series else []
    points = _growth_points(series.labels, values)

    message = None
    if len(points) < 2:
        message = (
            f"At least two {request.period.value} periods are needed to compute growth; "
            f"found {len(points)}."
        )

    return GrowthResponse(
        date_column=request.date_column,
        period=request.period,
        metric=request.metric,
        column=request.column,
        current=points[-1] if points else None,
        points=points,
        message=message,
    )


# --- Segmentation, ranking, contribution -------------------------------------


def _grouped_metric(
    frame: pd.DataFrame,
    dimension: str,
    metric: MetricType,
    column: str | None,
) -> pd.Series:
    require_column(frame, dimension)
    grouped = frame.groupby(dimension, dropna=False)
    reduced = grouped.apply(
        lambda chunk: compute_metric(chunk, metric, column), include_groups=False
    )
    return reduced.dropna()


def build_segment(frame: pd.DataFrame, request: SegmentRequest) -> SegmentResponse:
    """Metric broken down by a categorical dimension."""
    working = apply_filters(frame, request.filters)
    reduced = _grouped_metric(working, request.dimension, request.metric, request.column)

    total = _safe(reduced.sum()) if not reduced.empty else None
    ordered = reduced.sort_values(ascending=request.sort is SortDirection.ASC)
    limited = ordered.head(request.limit)

    return SegmentResponse(
        dimension=request.dimension,
        metric=request.metric,
        column=request.column,
        total=total,
        rows=[
            SegmentRow(
                label=_label(index),
                value=_safe(value),
                # Share of the overall total, not of the truncated page.
                percentage=(
                    _safe((value / total) * 100) if total not in (None, 0) else None
                ),
            )
            for index, value in limited.items()
        ],
        group_count=int(len(reduced)),
        truncated=len(reduced) > len(limited),
    )


def build_contribution(frame: pd.DataFrame, request: SegmentRequest) -> ContributionResponse:
    """Share of total per group, with a running cumulative percentage."""
    working = apply_filters(frame, request.filters)
    reduced = _grouped_metric(working, request.dimension, request.metric, request.column)

    total = _safe(reduced.sum()) if not reduced.empty else None
    # Contribution is only meaningful largest-first.
    ordered = reduced.sort_values(ascending=False).head(request.limit)

    rows: list[ContributionRow] = []
    cumulative = 0.0
    for index, value in ordered.items():
        share = (value / total) * 100 if total not in (None, 0) else None
        if share is not None:
            cumulative += share
        rows.append(
            ContributionRow(
                label=_label(index),
                value=_safe(value),
                percentage=_safe(share),
                cumulative_percentage=_safe(cumulative) if share is not None else None,
            )
        )

    return ContributionResponse(
        dimension=request.dimension,
        metric=request.metric,
        column=request.column,
        total=total,
        rows=rows,
        group_count=int(len(reduced)),
    )


# --- ABC analysis ------------------------------------------------------------


def build_abc(frame: pd.DataFrame, request: AbcRequest) -> AbcResponse:
    """Classify groups by cumulative contribution using configurable cut-offs."""
    if request.b_threshold <= request.a_threshold:
        raise ValidationError("The B threshold must be greater than the A threshold.")

    working = apply_filters(frame, request.filters)
    reduced = _grouped_metric(working, request.dimension, request.metric, request.column)
    # Negative contributions make cumulative shares meaningless.
    reduced = reduced[reduced > 0]

    if reduced.empty:
        raise ValidationError(
            f"No positive '{request.metric.value}' values found for '{request.dimension}'."
        )

    ordered = reduced.sort_values(ascending=False)
    total = float(ordered.sum())

    rows: list[AbcRow] = []
    cumulative = 0.0
    for index, value in ordered.items():
        share = (float(value) / total) * 100
        cumulative += share
        abc_class = (
            "A" if cumulative <= request.a_threshold
            else "B" if cumulative <= request.b_threshold
            else "C"
        )
        rows.append(
            AbcRow(
                label=_label(index),
                value=float(value),
                percentage=round(share, 4),
                cumulative_percentage=round(cumulative, 4),
                abc_class=abc_class,
            )
        )

    summary: list[AbcClassSummary] = []
    for abc_class in ("A", "B", "C"):
        members = [row for row in rows if row.abc_class == abc_class]
        class_total = sum(row.value for row in members)
        summary.append(
            AbcClassSummary(
                abc_class=abc_class,
                item_count=len(members),
                total_value=round(class_total, 4),
                percentage_of_total=round((class_total / total) * 100, 4) if total else 0.0,
                percentage_of_items=round((len(members) / len(rows)) * 100, 4) if rows else 0.0,
            )
        )

    return AbcResponse(
        dimension=request.dimension,
        metric=request.metric,
        column=request.column,
        total=round(total, 4),
        a_threshold=request.a_threshold,
        b_threshold=request.b_threshold,
        rows=rows,
        summary=summary,
    )


# --- Entity analysis ---------------------------------------------------------


def build_entity_analysis(frame: pd.DataFrame, request: EntityRequest) -> EntityResponse:
    """Per-identifier behaviour. The identifier column is always user-selected."""
    working = apply_filters(frame, request.filters)
    entity = require_column(working, request.entity_column)

    present = working.dropna(subset=[entity])
    if present.empty:
        raise ValidationError(f"Column '{request.entity_column}' has no values.")

    if request.value_column:
        require_column(working, request.value_column)
        detected = detect_type(working[request.value_column])
        if detected not in NUMERIC_TYPES:
            raise ValidationError(
                f"Value column '{request.value_column}' must be numeric, "
                f"but it is {detected.value}."
            )

    grouped = present.groupby(entity, dropna=True)
    record_counts = grouped.size()

    unique_entities = int(len(record_counts))
    repeat_entities = int((record_counts > 1).sum())
    one_time_entities = unique_entities - repeat_entities

    totals: pd.Series | None = None
    if request.value_column:
        totals = grouped[request.value_column].apply(
            lambda values: pd.to_numeric(values, errors="coerce").sum()
        )

    transactions: pd.Series | None = None
    if request.transaction_column:
        require_column(working, request.transaction_column)
        transactions = grouped[request.transaction_column].nunique()

    # Rank by value when available, otherwise by activity.
    ranking = totals if totals is not None else record_counts
    top = ranking.sort_values(ascending=False).head(request.limit)

    rows: list[EntityRow] = []
    for index in top.index:
        records = int(record_counts.loc[index])
        total_value = _safe(totals.loc[index]) if totals is not None else None
        rows.append(
            EntityRow(
                entity=_label(index),
                record_count=records,
                transaction_count=(
                    int(transactions.loc[index]) if transactions is not None else None
                ),
                total_value=total_value,
                average_value=(
                    _safe(total_value / records) if total_value is not None and records else None
                ),
            )
        )

    return EntityResponse(
        entity_column=request.entity_column,
        value_column=request.value_column,
        unique_entities=unique_entities,
        repeat_entities=repeat_entities,
        one_time_entities=one_time_entities,
        average_records_per_entity=_safe(record_counts.mean()),
        average_value_per_entity=(
            _safe(totals.sum() / unique_entities)
            if totals is not None and unique_entities
            else None
        ),
        top_entities=rows,
    )


# --- Distribution ------------------------------------------------------------


def build_distribution(frame: pd.DataFrame, request: DistributionRequest) -> DistributionResponse:
    """Descriptive statistics plus histogram buckets for a numeric column."""
    working = apply_filters(frame, request.filters)
    require_column(working, request.column)

    detected = detect_type(working[request.column])
    if detected not in NUMERIC_TYPES:
        raise ValidationError(
            f"Distribution analysis needs a numeric column, but '{request.column}' "
            f"is {detected.value}."
        )

    values = pd.to_numeric(working[request.column], errors="coerce").dropna()
    if values.empty:
        raise ValidationError(f"Column '{request.column}' has no numeric values.")

    buckets: list[DistributionBucket] = []
    if values.nunique() > 1:
        counts, edges = pd.cut(values, bins=request.bins, retbins=True)
        frequencies = counts.value_counts().sort_index()
        for position, count in enumerate(frequencies.tolist()):
            buckets.append(
                DistributionBucket(
                    label=f"{edges[position]:.2f} – {edges[position + 1]:.2f}",
                    count=int(count),
                    lower=float(edges[position]),
                    upper=float(edges[position + 1]),
                )
            )

    return DistributionResponse(
        column=request.column,
        count=int(len(values)),
        mean=_safe(values.mean()),
        median=_safe(values.median()),
        minimum=_safe(values.min()),
        maximum=_safe(values.max()),
        std_dev=_safe(values.std()) if len(values) > 1 else None,
        percentiles={
            f"p{int(percentile * 100)}": _safe(values.quantile(percentile))
            for percentile in PERCENTILES
        },
        buckets=buckets,
    )


# --- Column roles and KPI suggestions ----------------------------------------


def describe_columns(frame: pd.DataFrame) -> list[ColumnRole]:
    """Classify each column by what it can be used for."""
    roles: list[ColumnRole] = []
    row_count = max(len(frame), 1)

    for name in frame.columns:
        column = str(name)
        series = frame[name]
        detected = detect_type(series)
        distinct = int(series.nunique(dropna=True))

        numeric = detected in NUMERIC_TYPES
        temporal = detected is DetectedType.DATETIME
        name_is_id = bool(_ID_HINT.search(column))
        uniqueness = distinct / row_count

        if numeric:
            # A numeric column is a key only when it is named like one, or is
            # an integer that is effectively unique per row (1, 2, 3, ...).
            # Cardinality alone must NOT decide this: a revenue column is often
            # unique per row too, and summing it is exactly the point.
            identifier = name_is_id or (
                detected is DetectedType.INTEGER
                and distinct > 1
                and uniqueness >= NEAR_UNIQUE_RATIO
            )
        else:
            # A date is a time axis, not a key, however unique its values are.
            identifier = (
                not temporal
                and distinct > 1
                and (name_is_id or distinct > MAX_DIMENSION_CARDINALITY or uniqueness > 0.9)
            )

        categorical = (
            not numeric
            and not temporal
            and 0 < distinct <= MAX_DIMENSION_CARDINALITY
            and not identifier
        )
        # Only a non-identifier numeric column is worth summing or averaging.
        measure = numeric and not identifier

        roles.append(
            ColumnRole(
                name=column,
                dtype=detected.value,
                numeric=numeric,
                categorical=categorical,
                temporal=temporal,
                identifier=identifier,
                measure=measure,
            )
        )

    return roles
