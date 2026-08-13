"""Deterministic dataset profiling.

Pure computation over a DataFrame - no database, no HTTP, no LLM. The same
input always produces the same profile.

NaN/Inf are converted to ``None`` throughout: they are not valid JSON, and a
null-heavy or entirely empty column must profile safely rather than raise.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import pandas as pd

from app.schemas.profiling import (
    CategoricalStats,
    ColumnProfile,
    DatasetProfile,
    DateTimeStats,
    DetectedType,
    NumericStats,
    ValueCount,
)

#: Categorical `top_values` is capped so a high-cardinality column cannot
#: return an unbounded payload.
TOP_VALUES_LIMIT = 10

#: A string column is treated as dates only when at least this share of its
#: non-null values parse, which keeps arbitrary text from being misclassified.
DATE_PARSE_THRESHOLD = 0.9
#: Below this many non-null values, date inference is not attempted at all.
DATE_MIN_SAMPLE = 5


def _safe_number(value: Any) -> float | None:
    """Convert a numpy/pandas scalar to a JSON-safe float, or None."""
    if value is None or value is pd.NaT:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _percentage(part: int, whole: int) -> float:
    return round((part / whole) * 100, 2) if whole else 0.0


def _looks_like_dates(series: pd.Series) -> bool:
    """Conservative date detection for object columns.

    Purely numeric strings are rejected: pandas would happily read "2024" or
    "1000" as a date, which would misclassify identifiers and amounts.
    """
    non_null = series.dropna()
    if len(non_null) < DATE_MIN_SAMPLE:
        return False

    as_text = non_null.astype(str).str.strip()
    if as_text.str.fullmatch(r"[-+]?\d*\.?\d+").fillna(False).all():
        return False

    # Require a date-ish shape: digits with separators, or a month name.
    date_shaped = as_text.str.contains(
        r"(?:\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})"
        r"|(?:\d{1,2}\s*[A-Za-z]{3,})"
        r"|(?:[A-Za-z]{3,}\s*\d{1,2})",
        regex=True,
        na=False,
    )
    if date_shaped.mean() < DATE_PARSE_THRESHOLD:
        return False

    parsed = pd.to_datetime(as_text, errors="coerce", format="mixed", dayfirst=False)
    return bool(parsed.notna().mean() >= DATE_PARSE_THRESHOLD)


def detect_type(series: pd.Series) -> DetectedType:
    """Classify a column into the normalised type vocabulary."""
    if series.dropna().empty:
        return DetectedType.EMPTY
    if pd.api.types.is_bool_dtype(series):
        return DetectedType.BOOLEAN
    if pd.api.types.is_integer_dtype(series):
        return DetectedType.INTEGER
    if pd.api.types.is_float_dtype(series):
        return DetectedType.FLOAT
    if pd.api.types.is_datetime64_any_dtype(series):
        return DetectedType.DATETIME
    if pd.api.types.is_object_dtype(series) and _looks_like_dates(series):
        return DetectedType.DATETIME
    return DetectedType.STRING


def _numeric_stats(series: pd.Series) -> NumericStats:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        # Null-heavy or non-convertible: every statistic is undefined.
        return NumericStats()

    return NumericStats(
        minimum=_safe_number(values.min()),
        maximum=_safe_number(values.max()),
        mean=_safe_number(values.mean()),
        median=_safe_number(values.median()),
        # Standard deviation is undefined for a single observation.
        std_dev=_safe_number(values.std()) if len(values) > 1 else None,
        sum=_safe_number(values.sum()),
        percentile_25=_safe_number(values.quantile(0.25)),
        percentile_50=_safe_number(values.quantile(0.50)),
        percentile_75=_safe_number(values.quantile(0.75)),
    )


def _categorical_stats(series: pd.Series, non_null_count: int) -> CategoricalStats:
    non_null = series.dropna()
    if non_null.empty:
        return CategoricalStats(unique_count=0)

    counts = non_null.astype(str).value_counts()
    top = counts.head(TOP_VALUES_LIMIT)

    return CategoricalStats(
        unique_count=int(non_null.nunique()),
        most_frequent_value=str(counts.index[0]),
        most_frequent_count=int(counts.iloc[0]),
        most_frequent_percentage=_percentage(int(counts.iloc[0]), non_null_count),
        top_values=[
            ValueCount(
                value=str(value),
                count=int(count),
                percentage=_percentage(int(count), non_null_count),
            )
            for value, count in top.items()
        ],
    )


def _datetime_stats(series: pd.Series) -> DateTimeStats:
    parsed = (
        series
        if pd.api.types.is_datetime64_any_dtype(series)
        else pd.to_datetime(series, errors="coerce", format="mixed")
    )
    valid = parsed.dropna()

    return DateTimeStats(
        minimum=valid.min().to_pydatetime() if not valid.empty else None,
        maximum=valid.max().to_pydatetime() if not valid.empty else None,
        unique_count=int(valid.nunique()),
        # Counts values that are missing *or* unparseable as dates.
        missing_count=int(len(series) - len(valid)),
    )


def profile_column(series: pd.Series, row_count: int) -> ColumnProfile:
    detected = detect_type(series)
    null_count = int(series.isna().sum())
    non_null_count = row_count - null_count

    profile = ColumnProfile(
        column_name=str(series.name),
        detected_data_type=detected,
        null_count=null_count,
        null_percentage=_percentage(null_count, row_count),
        non_null_count=non_null_count,
        unique_count=int(series.nunique(dropna=True)),
        unique_percentage=_percentage(int(series.nunique(dropna=True)), non_null_count),
    )

    if detected in (DetectedType.INTEGER, DetectedType.FLOAT):
        profile.numeric = _numeric_stats(series)
    elif detected is DetectedType.DATETIME:
        profile.datetime_stats = _datetime_stats(series)
    elif detected in (DetectedType.STRING, DetectedType.BOOLEAN):
        profile.categorical = _categorical_stats(series, non_null_count)

    return profile


def profile_frame(
    frame: pd.DataFrame,
    *,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> DatasetProfile:
    """Build the full profile for a DataFrame."""
    row_count = int(len(frame))
    column_count = int(len(frame.columns))
    total_cells = row_count * column_count

    duplicate_count = int(frame.duplicated().sum()) if row_count else 0
    missing_cells = int(frame.isna().sum().sum()) if total_cells else 0

    return DatasetProfile(
        dataset_id=dataset_id,
        version_id=version_id,
        row_count=row_count,
        column_count=column_count,
        duplicate_row_count=duplicate_count,
        duplicate_row_percentage=_percentage(duplicate_count, row_count),
        missing_cell_count=missing_cells,
        missing_cell_percentage=_percentage(missing_cells, total_cells),
        columns=[profile_column(frame[name], row_count) for name in frame.columns],
    )
