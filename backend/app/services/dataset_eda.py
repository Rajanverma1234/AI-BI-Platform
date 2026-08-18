"""Exploratory data analysis: per-type summaries and correlation.

Deterministic statistics only - no models, no inference beyond standard
descriptive measures.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import pandas as pd

from app.schemas.profiling import DetectedType
from app.schemas.visualization import (
    CategoricalSummary,
    CorrelationResponse,
    DateSummary,
    EdaSummaryResponse,
    NumericSummary,
)
from app.services.dataset_profiling import TOP_VALUES_LIMIT, detect_type
from app.services.dataset_query import NUMERIC_TYPES

#: Pearson needs at least two paired observations to be defined.
MIN_CORRELATION_ROWS = 2
MIN_CORRELATION_COLUMNS = 2


def _safe(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def build_summary(
    frame: pd.DataFrame,
    *,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> EdaSummaryResponse:
    """Summarise each column according to its detected type."""
    numeric: list[NumericSummary] = []
    categorical: list[CategoricalSummary] = []
    dates: list[DateSummary] = []

    for name in frame.columns:
        column = str(name)
        series = frame[name]
        detected = detect_type(series)

        if detected in NUMERIC_TYPES:
            values = pd.to_numeric(series, errors="coerce").dropna()
            numeric.append(
                NumericSummary(
                    column=column,
                    mean=_safe(values.mean()) if not values.empty else None,
                    median=_safe(values.median()) if not values.empty else None,
                    minimum=_safe(values.min()) if not values.empty else None,
                    maximum=_safe(values.max()) if not values.empty else None,
                    # Undefined for a single observation.
                    std_dev=_safe(values.std()) if len(values) > 1 else None,
                )
            )

        elif detected is DetectedType.DATETIME:
            parsed = pd.to_datetime(series, errors="coerce", format="mixed").dropna()
            if parsed.empty:
                dates.append(DateSummary(column=column))
            else:
                minimum, maximum = parsed.min(), parsed.max()
                dates.append(
                    DateSummary(
                        column=column,
                        minimum=minimum.isoformat(),
                        maximum=maximum.isoformat(),
                        range_days=int((maximum - minimum).days),
                    )
                )

        elif detected in (DetectedType.STRING, DetectedType.BOOLEAN):
            non_null = series.dropna()
            counts = non_null.astype(str).value_counts().head(TOP_VALUES_LIMIT)
            total = int(len(non_null))
            categorical.append(
                CategoricalSummary(
                    column=column,
                    unique_count=int(non_null.nunique()),
                    top_values=[
                        {
                            "value": str(value),
                            "count": int(count),
                            "percentage": round((int(count) / total) * 100, 2) if total else 0.0,
                        }
                        for value, count in counts.items()
                    ],
                )
            )

    return EdaSummaryResponse(
        dataset_id=dataset_id,
        version_id=version_id,
        row_count=int(len(frame)),
        numeric=numeric,
        categorical=categorical,
        dates=dates,
    )


def build_correlation(
    frame: pd.DataFrame,
    *,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    method: str = "pearson",
) -> CorrelationResponse:
    """Pairwise correlation across numeric columns.

    Degenerate inputs are reported rather than raised: constant columns have no
    defined correlation, and fewer than two usable columns simply yields an
    empty matrix with an explanation.
    """
    excluded: list[dict[str, str]] = []
    usable: dict[str, pd.Series] = {}

    for name in frame.columns:
        column = str(name)
        if detect_type(frame[name]) not in NUMERIC_TYPES:
            continue

        values = pd.to_numeric(frame[name], errors="coerce")
        non_null = values.dropna()

        if len(non_null) < MIN_CORRELATION_ROWS:
            excluded.append({"column": column, "reason": "not enough non-null values"})
            continue
        if non_null.nunique() <= 1:
            # Zero variance: correlation is undefined, not zero.
            excluded.append({"column": column, "reason": "constant column"})
            continue

        usable[column] = values

    if len(usable) < MIN_CORRELATION_COLUMNS:
        return CorrelationResponse(
            dataset_id=dataset_id,
            version_id=version_id,
            method=method,
            columns=[],
            matrix=[],
            excluded=excluded,
            message=(
                "At least two numeric columns with varying values are needed "
                "to compute correlations."
            ),
        )

    # Pandas computes pairwise-complete correlations, so missing values in one
    # column do not discard the whole row for other pairs.
    matrix = pd.DataFrame(usable).corr(method=method)  # type: ignore[arg-type]
    columns = [str(name) for name in matrix.columns]

    return CorrelationResponse(
        dataset_id=dataset_id,
        version_id=version_id,
        method=method,
        columns=columns,
        matrix=[[_safe(value) for value in matrix[column].tolist()] for column in matrix.columns],
        excluded=excluded,
        message=None,
    )
