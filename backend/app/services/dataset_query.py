"""Filtering, aggregation and preview over a dataset frame.

Security posture: no column name or value from the client is ever interpolated
into a query string, `eval`, or `DataFrame.query`. Each filter is validated
against the actual frame (the column must exist) and then mapped onto a pandas
boolean mask, so a crafted column name can only ever produce a 4xx error.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.schemas.profiling import DetectedType
from app.schemas.visualization import (
    NUMERIC_ONLY_AGGREGATIONS,
    Aggregation,
    AggregationSpec,
    FilterCondition,
    FilterLogic,
    FilterOperator,
    FilterSet,
)
from app.services.dataset_profiling import detect_type

NUMERIC_TYPES = frozenset({DetectedType.INTEGER, DetectedType.FLOAT})


def require_column(frame: pd.DataFrame, column: str) -> str:
    """Validate a client-supplied column name against the real frame."""
    if column not in frame.columns:
        raise ValidationError(f"Unknown column '{column}'.")
    return column


def json_safe(value: Any) -> Any:
    """Convert a cell to something JSON-serialisable; NaN/NaT become null."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def rows_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a frame to JSON-safe records, preserving nulls as null."""
    return [
        {str(column): json_safe(row[column]) for column in frame.columns}
        for _, row in frame.iterrows()
    ]


def _coerce_numeric(value: Any, column: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Filter on '{column}' expects a numeric value, got {value!r}."
        ) from exc


def _comparable(series: pd.Series, value: Any, column: str) -> tuple[pd.Series, Any]:
    """Align a series and a filter value for an ordered comparison.

    Dates compare as timestamps, everything else as numbers, so ">" on a text
    column fails loudly instead of comparing strings lexicographically.
    """
    detected = detect_type(series)

    if detected is DetectedType.DATETIME:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
        bound = pd.to_datetime(value, errors="coerce")
        if pd.isna(bound):
            raise ValidationError(f"Filter on '{column}' expects a date value.")
        return parsed, bound

    if detected in NUMERIC_TYPES:
        return pd.to_numeric(series, errors="coerce"), _coerce_numeric(value, column)

    raise ValidationError(
        f"Column '{column}' is {detected.value}; ordered comparisons need a "
        "numeric or date column."
    )


def _condition_mask(frame: pd.DataFrame, condition: FilterCondition) -> pd.Series:
    """Translate one condition into a boolean mask."""
    column = require_column(frame, condition.column)
    series = frame[column]

    match condition.operator:
        case FilterOperator.IS_NULL:
            return series.isna()
        case FilterOperator.IS_NOT_NULL:
            return series.notna()

    if condition.value is None:
        raise ValidationError(
            f"Filter on '{column}' with operator '{condition.operator.value}' needs a value."
        )

    match condition.operator:
        case FilterOperator.EQUALS:
            return series.astype(str) == str(condition.value)
        case FilterOperator.NOT_EQUALS:
            return series.astype(str) != str(condition.value)
        case FilterOperator.CONTAINS:
            # regex=False so user input is treated as a literal substring.
            return series.astype(str).str.contains(
                str(condition.value), case=False, regex=False, na=False
            )
        case FilterOperator.BETWEEN:
            if condition.value_to is None:
                raise ValidationError(f"'between' on '{column}' needs both bounds.")
            values, low = _comparable(series, condition.value, column)
            _, high = _comparable(series, condition.value_to, column)
            if low > high:
                low, high = high, low
            return (values >= low) & (values <= high)
        case FilterOperator.GREATER_THAN:
            values, bound = _comparable(series, condition.value, column)
            return values > bound
        case FilterOperator.GREATER_OR_EQUAL:
            values, bound = _comparable(series, condition.value, column)
            return values >= bound
        case FilterOperator.LESS_THAN:
            values, bound = _comparable(series, condition.value, column)
            return values < bound
        case FilterOperator.LESS_OR_EQUAL:
            values, bound = _comparable(series, condition.value, column)
            return values <= bound

    raise ValidationError(f"Unsupported filter operator '{condition.operator}'.")


def apply_filters(frame: pd.DataFrame, filters: FilterSet | None) -> pd.DataFrame:
    """Apply a filter set, combining conditions with AND or OR."""
    if filters is None or not filters.conditions:
        return frame

    masks = [_condition_mask(frame, condition) for condition in filters.conditions]

    combined = masks[0]
    for mask in masks[1:]:
        combined = (combined & mask) if filters.logic is FilterLogic.AND else (combined | mask)

    return frame.loc[combined.fillna(False)]


# --- Aggregation -------------------------------------------------------------


def validate_aggregation(frame: pd.DataFrame, column: str, aggregation: Aggregation) -> None:
    """Reject aggregations that make no sense for the column's type.

    COUNT applies to anything; SUM/MEAN/MEDIAN require numbers. MIN/MAX are
    allowed on dates as well as numbers.
    """
    require_column(frame, column)
    if aggregation is Aggregation.COUNT:
        return

    detected = detect_type(frame[column])

    if aggregation in NUMERIC_ONLY_AGGREGATIONS and detected not in NUMERIC_TYPES:
        raise ValidationError(
            f"'{aggregation.value}' requires a numeric column, but '{column}' "
            f"is {detected.value}."
        )

    if aggregation in (Aggregation.MIN, Aggregation.MAX) and detected not in (
        *NUMERIC_TYPES,
        DetectedType.DATETIME,
    ):
        raise ValidationError(
            f"'{aggregation.value}' requires a numeric or date column, but "
            f"'{column}' is {detected.value}."
        )


def _aggregate_series(series: pd.Series, aggregation: Aggregation) -> Any:
    if aggregation is Aggregation.COUNT:
        return int(series.count())

    values = pd.to_numeric(series, errors="coerce")
    match aggregation:
        case Aggregation.SUM:
            return values.sum()
        case Aggregation.MEAN:
            return values.mean()
        case Aggregation.MEDIAN:
            return values.median()
        case Aggregation.MIN:
            return values.min()
        case Aggregation.MAX:
            return values.max()
    return None


def aggregate(
    frame: pd.DataFrame,
    group_by: list[str],
    aggregations: list[AggregationSpec],
) -> pd.DataFrame:
    """Group and aggregate. Deterministic: groups are sorted by key."""
    for column in group_by:
        require_column(frame, column)
    for spec in aggregations:
        validate_aggregation(frame, spec.column, spec.aggregation)

    def alias(spec: AggregationSpec) -> str:
        return spec.alias or f"{spec.aggregation.value}_{spec.column}"

    def reduce_chunk(chunk: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                alias(spec): _aggregate_series(chunk[spec.column], spec.aggregation)
                for spec in aggregations
            }
        )

    if not group_by:
        return pd.DataFrame([reduce_chunk(frame)])

    grouped = frame.groupby(group_by, dropna=False, sort=True)
    return grouped.apply(reduce_chunk, include_groups=False).reset_index()
