"""Chart data construction and rule-based chart suggestions.

Everything here is deterministic: chart type selection is a fixed decision
table over detected column types, never a model. The output is pure data -
colours, sizing and rendering belong to the frontend.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.schemas.profiling import DetectedType
from app.schemas.visualization import (
    Aggregation,
    BoxPlotStats,
    ChartConfig,
    ChartDataResponse,
    ChartSeries,
    ChartSuggestion,
    ChartType,
    ScatterPoint,
)
from app.services.dataset_profiling import detect_type
from app.services.dataset_query import (
    NUMERIC_TYPES,
    apply_filters,
    require_column,
    validate_aggregation,
)

#: Categories beyond the configured limit are collapsed into this bucket.
OTHER_LABEL = "Other"
#: Scatter charts stop here so a large dataset cannot flood the browser.
MAX_SCATTER_POINTS = 2000


def _safe(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    require_column(frame, column)
    if detect_type(frame[column]) not in NUMERIC_TYPES:
        raise ValidationError(f"Column '{column}' is not numeric.")
    return pd.to_numeric(frame[column], errors="coerce")


def _require(config: ChartConfig, field: str, value: str | None) -> str:
    if not value:
        raise ValidationError(f"{config.chart_type.value} charts require a {field}.")
    return value


def _limit_categories(series: pd.Series, limit: int) -> pd.Series:
    """Keep the top `limit` categories by value, summing the rest into Other."""
    if len(series) <= limit:
        return series
    top = series.iloc[:limit]
    remainder = series.iloc[limit:].sum()
    return pd.concat([top, pd.Series({OTHER_LABEL: remainder})])


def _aggregate_by_category(
    frame: pd.DataFrame, config: ChartConfig, x_column: str, y_column: str | None
) -> pd.Series:
    """Group by the category column and reduce the value column."""
    if config.aggregation is Aggregation.COUNT and y_column is None:
        # Counting rows per category needs no value column.
        counts = frame.groupby(x_column, dropna=False).size()
    else:
        column = _require(config, "value column", y_column)
        validate_aggregation(frame, column, config.aggregation)
        counts = frame.groupby(x_column, dropna=False)[column].agg(
            lambda values: _reduce(values, config.aggregation)
        )

    counts.index = counts.index.map(lambda value: "(empty)" if pd.isna(value) else str(value))
    # Sort largest-first so the "top N + Other" cut is meaningful.
    return _limit_categories(counts.sort_values(ascending=False), config.max_categories)


def _reduce(series: pd.Series, aggregation: Aggregation) -> Any:
    if aggregation is Aggregation.COUNT:
        return int(series.count())
    values = pd.to_numeric(series, errors="coerce")
    return {
        Aggregation.SUM: values.sum,
        Aggregation.MEAN: values.mean,
        Aggregation.MEDIAN: values.median,
        Aggregation.MIN: values.min,
        Aggregation.MAX: values.max,
    }[aggregation]()


def _category_chart(frame: pd.DataFrame, config: ChartConfig) -> ChartDataResponse:
    """Bar / line / area / pie / donut all share category + value shape."""
    x_column = _require(config, "category column", config.x_column)
    require_column(frame, x_column)

    # A second grouping produces one series per group value.
    if config.group_by and config.chart_type in (ChartType.BAR, ChartType.LINE, ChartType.AREA):
        group_column = require_column(frame, config.group_by)
        y_column = _require(config, "value column", config.y_column)
        validate_aggregation(frame, y_column, config.aggregation)

        pivot = frame.pivot_table(
            index=x_column,
            columns=group_column,
            values=y_column,
            aggfunc=lambda s: _reduce(s, config.aggregation),
            dropna=False,
        ).sort_index()

        labels = [str(label) for label in pivot.index]
        series = [
            ChartSeries(
                name=str(name),
                data=[_safe(value) for value in pivot[name].tolist()],
            )
            for name in pivot.columns[: config.max_categories]
        ]
        return ChartDataResponse(
            chart_type=config.chart_type,
            title=config.title,
            x_axis=config.x_axis_label or x_column,
            y_axis=config.y_axis_label or y_column,
            labels=labels,
            series=series,
            metadata={"grouped_by": group_column, "aggregation": config.aggregation.value},
        )

    values = _aggregate_by_category(frame, config, x_column, config.y_column)

    # Time-ordered charts read left-to-right by X, not by magnitude.
    if config.chart_type in (ChartType.LINE, ChartType.AREA):
        values = values.sort_index()

    y_label = config.y_axis_label or (
        config.y_column or ("count" if config.aggregation is Aggregation.COUNT else "value")
    )
    return ChartDataResponse(
        chart_type=config.chart_type,
        title=config.title,
        x_axis=config.x_axis_label or x_column,
        y_axis=y_label,
        labels=[str(label) for label in values.index],
        series=[
            ChartSeries(
                name=y_label,
                data=[_safe(value) for value in values.tolist()],
            )
        ],
        metadata={
            "aggregation": config.aggregation.value,
            "category_count": int(len(values)),
        },
    )


def _scatter_chart(frame: pd.DataFrame, config: ChartConfig) -> ChartDataResponse:
    x_column = _require(config, "numeric X column", config.x_column)
    y_column = _require(config, "numeric Y column", config.y_column)

    pair = pd.DataFrame({"x": _numeric(frame, x_column), "y": _numeric(frame, y_column)}).dropna()
    truncated = len(pair) > MAX_SCATTER_POINTS
    if truncated:
        pair = pair.head(MAX_SCATTER_POINTS)

    return ChartDataResponse(
        chart_type=ChartType.SCATTER,
        title=config.title,
        x_axis=config.x_axis_label or x_column,
        y_axis=config.y_axis_label or y_column,
        points=[ScatterPoint(x=float(row.x), y=float(row.y)) for row in pair.itertuples()],
        metadata={"point_count": int(len(pair)), "truncated": truncated},
    )


def _histogram_chart(frame: pd.DataFrame, config: ChartConfig) -> ChartDataResponse:
    column = _require(config, "numeric column", config.x_column or config.y_column)
    values = _numeric(frame, column).dropna()
    if values.empty:
        raise ValidationError(f"Column '{column}' has no numeric values to plot.")

    counts, edges = pd.cut(values, bins=config.bins, retbins=True)
    frequencies = counts.value_counts().sort_index()

    labels = [
        f"{edges[index]:.2f} – {edges[index + 1]:.2f}" for index in range(len(edges) - 1)
    ]
    return ChartDataResponse(
        chart_type=ChartType.HISTOGRAM,
        title=config.title,
        x_axis=config.x_axis_label or column,
        y_axis=config.y_axis_label or "frequency",
        labels=labels,
        series=[ChartSeries(name="frequency", data=[float(v) for v in frequencies.tolist()])],
        metadata={"bins": config.bins, "total_values": int(len(values))},
    )


def _box_stats(values: pd.Series, label: str) -> BoxPlotStats | None:
    clean = values.dropna()
    if clean.empty:
        return None

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = clean[(clean >= lower) & (clean <= upper)]

    return BoxPlotStats(
        label=label,
        # Whiskers stop at the last value inside the fence, as convention.
        minimum=float(inside.min()) if not inside.empty else float(clean.min()),
        q1=q1,
        median=float(clean.median()),
        q3=q3,
        maximum=float(inside.max()) if not inside.empty else float(clean.max()),
        outlier_count=int(len(clean) - len(inside)),
    )


def _box_chart(frame: pd.DataFrame, config: ChartConfig) -> ChartDataResponse:
    column = _require(config, "numeric column", config.y_column or config.x_column)
    values = _numeric(frame, column)

    boxes: list[BoxPlotStats] = []
    if config.group_by:
        group_column = require_column(frame, config.group_by)
        grouped = pd.DataFrame({"value": values, "group": frame[group_column]})
        for label, chunk in grouped.groupby("group", dropna=False, sort=True):
            stats = _box_stats(chunk["value"], "(empty)" if pd.isna(label) else str(label))
            if stats:
                boxes.append(stats)
            if len(boxes) >= config.max_categories:
                break
    else:
        stats = _box_stats(values, column)
        if stats:
            boxes.append(stats)

    if not boxes:
        raise ValidationError(f"Column '{column}' has no numeric values to plot.")

    return ChartDataResponse(
        chart_type=ChartType.BOX,
        title=config.title,
        x_axis=config.x_axis_label or (config.group_by or column),
        y_axis=config.y_axis_label or column,
        boxes=boxes,
        metadata={"group_count": len(boxes)},
    )


def build_chart(frame: pd.DataFrame, config: ChartConfig) -> ChartDataResponse:
    """Validate the configuration and produce structured chart data."""
    filtered = apply_filters(frame, config.filters)

    if filtered.empty:
        raise ValidationError("No rows match the selected filters.")

    match config.chart_type:
        case ChartType.SCATTER:
            return _scatter_chart(filtered, config)
        case ChartType.HISTOGRAM:
            return _histogram_chart(filtered, config)
        case ChartType.BOX:
            return _box_chart(filtered, config)
        case _:
            return _category_chart(filtered, config)


# --- Rule-based suggestions --------------------------------------------------


def suggest_charts(frame: pd.DataFrame, limit: int = 8) -> list[ChartSuggestion]:
    """Deterministic chart suggestions from detected column types.

    Decision table (no AI):
      date + numeric        -> line
      categorical + numeric -> bar
      two numerics          -> scatter
      single numeric        -> histogram, box
      categorical alone     -> bar / pie of value counts
    """
    types = {str(name): detect_type(frame[name]) for name in frame.columns}
    numeric = [name for name, kind in types.items() if kind in NUMERIC_TYPES]
    dates = [name for name, kind in types.items() if kind is DetectedType.DATETIME]
    categorical = [
        name
        for name, kind in types.items()
        if kind in (DetectedType.STRING, DetectedType.BOOLEAN)
        # Identifier-like columns make useless categories.
        and 0 < frame[name].nunique(dropna=True) <= 50
    ]

    suggestions: list[ChartSuggestion] = []

    if dates and numeric:
        suggestions.append(
            ChartSuggestion(
                chart_type=ChartType.LINE,
                title=f"{numeric[0]} over {dates[0]}",
                reason="A date column combined with a numeric column plots well as a trend line.",
                config=ChartConfig(
                    chart_type=ChartType.LINE,
                    x_column=dates[0],
                    y_column=numeric[0],
                    aggregation=Aggregation.SUM,
                ),
            )
        )

    if categorical and numeric:
        suggestions.append(
            ChartSuggestion(
                chart_type=ChartType.BAR,
                title=f"{numeric[0]} by {categorical[0]}",
                reason="A categorical column with a numeric measure compares well as bars.",
                config=ChartConfig(
                    chart_type=ChartType.BAR,
                    x_column=categorical[0],
                    y_column=numeric[0],
                    aggregation=Aggregation.SUM,
                ),
            )
        )

    if len(numeric) >= 2:
        suggestions.append(
            ChartSuggestion(
                chart_type=ChartType.SCATTER,
                title=f"{numeric[1]} vs {numeric[0]}",
                reason="Two numeric columns show their relationship as a scatter plot.",
                config=ChartConfig(
                    chart_type=ChartType.SCATTER, x_column=numeric[0], y_column=numeric[1]
                ),
            )
        )

    for column in numeric[:2]:
        suggestions.append(
            ChartSuggestion(
                chart_type=ChartType.HISTOGRAM,
                title=f"Distribution of {column}",
                reason="A single numeric column shows its distribution as a histogram.",
                config=ChartConfig(chart_type=ChartType.HISTOGRAM, x_column=column),
            )
        )
        suggestions.append(
            ChartSuggestion(
                chart_type=ChartType.BOX,
                title=f"Spread of {column}",
                reason="A box plot summarises spread and outliers for a numeric column.",
                config=ChartConfig(chart_type=ChartType.BOX, y_column=column),
            )
        )

    for column in categorical[:2]:
        suggestions.append(
            ChartSuggestion(
                chart_type=ChartType.BAR,
                title=f"Count by {column}",
                reason="A categorical column alone is best shown as a distribution of counts.",
                config=ChartConfig(
                    chart_type=ChartType.BAR, x_column=column, aggregation=Aggregation.COUNT
                ),
            )
        )

    return suggestions[:limit]
