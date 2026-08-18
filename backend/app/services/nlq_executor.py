"""Deterministic execution of a validated QueryPlan.

The plan is dispatched through a fixed map of intent -> handler. There is no
``eval``, no ``exec``, no generated SQL and no dynamic attribute access: the
plan can only select columns and aggregations that ``nlq_planner.validate_plan``
has already checked against the dataset.

Aggregation and filtering reuse the existing analytics services.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.schemas.analytics import SegmentRequest, TimePeriod, TimeSeriesRequest
from app.schemas.nlq import (
    CalculationStep,
    ChartRecommendation,
    PlanMeasure,
    QueryIntent,
    QueryPlan,
    QueryResult,
    ResultColumn,
)
from app.schemas.visualization import ChartType, FilterCondition, FilterSet
from app.services import analytics_engine
from app.services.dataset_query import apply_filters

#: Never return more than this many rows regardless of the plan.
HARD_ROW_LIMIT = 500


def _filter_set(plan: QueryPlan) -> FilterSet | None:
    """Translate plan filters into the existing FilterSet contract."""
    if not plan.filters:
        return None
    return FilterSet(
        logic=plan.filter_logic,
        conditions=[
            FilterCondition(
                column=item.column,
                operator=item.operator,
                value=item.value,
                value_to=item.value_to,
            )
            for item in plan.filters
        ],
    )


def _measure_label(measure: PlanMeasure) -> str:
    if measure.alias:
        return measure.alias
    if measure.column is None:
        return "count"
    return f"{measure.aggregation.value} of {measure.column}"


# --- Intent handlers ---------------------------------------------------------


def _execute_metric(frame: pd.DataFrame, plan: QueryPlan) -> QueryResult:
    """One or more scalar values over the whole (filtered) dataset."""
    rows: dict[str, Any] = {}
    first_label: str | None = None
    first_value: float | None = None

    for measure in plan.measures:
        label = _measure_label(measure)
        value = analytics_engine.compute_metric(frame, measure.aggregation, measure.column)
        rows[label] = value
        if first_label is None:
            first_label, first_value = label, value

    return QueryResult(
        result_type=plan.intent,
        columns=[ResultColumn(name=label, role="measure") for label in rows],
        rows=[rows],
        row_count=1,
        metric_label=first_label,
        metric_value=first_value,
    )


def _execute_grouped(frame: pd.DataFrame, plan: QueryPlan) -> QueryResult:
    """Metric broken down by one dimension, optionally ranked."""
    dimension = plan.dimensions[0]
    measure = plan.measures[0]

    segment = analytics_engine.build_segment(
        frame,
        SegmentRequest(
            dimension=dimension,
            metric=measure.aggregation,
            column=measure.column,
            sort="desc" if plan.sort_desc else "asc",  # type: ignore[arg-type]
            limit=min(plan.limit, HARD_ROW_LIMIT),
        ),
    )

    label = _measure_label(measure)
    rows: list[dict[str, Any]] = []
    for position, row in enumerate(segment.rows, start=1):
        entry: dict[str, Any] = {dimension: row.label, label: row.value}
        if plan.intent is QueryIntent.RANK:
            entry["rank"] = position
        if row.percentage is not None:
            entry["share_%"] = row.percentage
        rows.append(entry)

    columns = [ResultColumn(name=dimension, role="dimension")]
    if plan.intent is QueryIntent.RANK:
        columns.append(ResultColumn(name="rank", role="dimension"))
    columns.append(ResultColumn(name=label, role="measure"))
    if rows and "share_%" in rows[0]:
        columns.append(ResultColumn(name="share_%", role="measure"))

    return QueryResult(
        result_type=plan.intent,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=segment.truncated,
    )


def _execute_comparison(frame: pd.DataFrame, plan: QueryPlan) -> QueryResult:
    """Same shape as a grouped result; filters usually narrow it to the pair."""
    result = _execute_grouped(frame, plan)
    return result.model_copy(update={"result_type": QueryIntent.COMPARISON})


def _execute_timeseries(frame: pd.DataFrame, plan: QueryPlan) -> QueryResult:
    if plan.date_column is None:
        raise ValidationError("A time-based question needs a date column.")

    measure = plan.measures[0]
    series = analytics_engine.build_time_series(
        frame,
        TimeSeriesRequest(
            date_column=plan.date_column,
            period=plan.date_period or TimePeriod.MONTH,
            metric=measure.aggregation,
            column=measure.column,
            max_points=min(plan.limit, HARD_ROW_LIMIT),
        ),
    )

    label = _measure_label(measure)
    points = series.series[0].points if series.series else []
    rows = [{"period": point.label, label: point.value} for point in points]

    return QueryResult(
        result_type=QueryIntent.TIMESERIES,
        columns=[
            ResultColumn(name="period", role="dimension"),
            ResultColumn(name=label, role="measure"),
        ],
        rows=rows,
        row_count=len(rows),
        truncated=series.truncated,
    )


#: Fixed dispatch table - the only operations a plan can trigger.
_HANDLERS: dict[QueryIntent, Callable[[pd.DataFrame, QueryPlan], QueryResult]] = {
    QueryIntent.METRIC: _execute_metric,
    QueryIntent.MULTI_METRIC: _execute_metric,
    QueryIntent.GROUP: _execute_grouped,
    QueryIntent.RANK: _execute_grouped,
    QueryIntent.COMPARISON: _execute_comparison,
    QueryIntent.TIMESERIES: _execute_timeseries,
}


def execute(frame: pd.DataFrame, plan: QueryPlan) -> QueryResult:
    """Run a validated plan and return a bounded, structured result."""
    filtered = apply_filters(frame, _filter_set(plan))

    if filtered.empty:
        raise ValidationError("No records match those conditions.")

    handler = _HANDLERS.get(plan.intent)
    if handler is None:  # pragma: no cover - the enum prevents this
        raise ValidationError(f"Unsupported question type '{plan.intent.value}'.")

    result = handler(filtered, plan)

    # Final guard: never hand back more rows than the ceiling allows.
    if len(result.rows) > HARD_ROW_LIMIT:
        return result.model_copy(
            update={"rows": result.rows[:HARD_ROW_LIMIT], "truncated": True}
        )
    return result


# --- Transparency ------------------------------------------------------------


def describe(plan: QueryPlan) -> list[CalculationStep]:
    """The auditable 'how this was calculated' breakdown."""
    steps = [
        CalculationStep(
            label="Metric",
            detail=", ".join(
                f"{measure.aggregation.value.upper()}({measure.column or '*'})"
                for measure in plan.measures
            ),
        )
    ]

    if plan.dimensions:
        steps.append(CalculationStep(label="Group by", detail=", ".join(plan.dimensions)))

    if plan.date_column:
        period = (plan.date_period or TimePeriod.MONTH).value
        steps.append(
            CalculationStep(label="Time grouping", detail=f"{plan.date_column} by {period}")
        )

    if plan.filters:
        steps.append(
            CalculationStep(
                label="Filters",
                detail=f" {plan.filter_logic.value.upper()} ".join(
                    f"{item.column} {item.operator.value.replace('_', ' ')}"
                    + (f" {item.value}" if item.value is not None else "")
                    + (f" and {item.value_to}" if item.value_to is not None else "")
                    for item in plan.filters
                ),
            )
        )

    if plan.intent in (QueryIntent.GROUP, QueryIntent.RANK, QueryIntent.COMPARISON):
        measure = plan.measures[0]
        steps.append(
            CalculationStep(
                label="Sort",
                detail=(
                    f"{_measure_label(measure)} "
                    f"{'descending' if plan.sort_desc else 'ascending'}"
                ),
            )
        )
        steps.append(CalculationStep(label="Limit", detail=str(plan.limit)))

    return steps


# --- Chart recommendation ----------------------------------------------------


def recommend_chart(plan: QueryPlan, result: QueryResult) -> ChartRecommendation | None:
    """Rule-based chart choice, shaped for the existing ChartRenderer."""
    if result.row_count == 0:
        return None

    measure_columns = [column.name for column in result.columns if column.role == "measure"]
    # share_% is supporting detail, not the value being charted.
    measure_columns = [name for name in measure_columns if name != "share_%"]
    if not measure_columns:
        return None
    value_key = measure_columns[0]

    if result.result_type is QueryIntent.TIMESERIES:
        chart_type, reason, x_axis = (
            ChartType.LINE,
            "A metric across time periods reads best as a trend line.",
            "period",
        )
    elif result.result_type in (QueryIntent.GROUP, QueryIntent.RANK, QueryIntent.COMPARISON):
        if result.row_count <= 6:
            chart_type = ChartType.PIE
            reason = "A small number of categories shows composition well as a pie chart."
        else:
            chart_type = ChartType.BAR
            reason = "Categories with a numeric measure compare well as bars."
        x_axis = plan.dimensions[0] if plan.dimensions else result.columns[0].name
    else:
        # A single metric is a KPI, not a chart.
        return None

    if plan.chart_type is not None:
        chart_type = plan.chart_type

    labels = [str(row.get(x_axis, "")) for row in result.rows]
    data = [row.get(value_key) for row in result.rows]

    return ChartRecommendation(
        chart_type=chart_type,
        reason=reason,
        x_axis=x_axis,
        y_axis=value_key,
        labels=labels,
        series=[{"name": value_key, "data": data}],
    )


# --- Deterministic answer ----------------------------------------------------


def describe_answer(question: str, plan: QueryPlan, result: QueryResult) -> str:
    """A readable answer built from the result, with no AI involved."""
    if result.result_type in (QueryIntent.METRIC, QueryIntent.MULTI_METRIC):
        parts = []
        for column in result.columns:
            value = result.rows[0].get(column.name)
            parts.append(
                f"{column.name} is {value:,.2f}" if isinstance(value, (int, float)) else
                f"{column.name} is not available"
            )
        return ". ".join(parts) + "."

    if result.result_type is QueryIntent.TIMESERIES and result.rows:
        series_measure = next(
            column.name for column in result.columns if column.role == "measure"
        )
        values = [
            (row["period"], row[series_measure])
            for row in result.rows
            if isinstance(row.get(series_measure), (int, float))
        ]
        if not values:
            return "No values were available for that period."
        highest = max(values, key=lambda item: item[1])
        lowest = min(values, key=lambda item: item[1])
        return (
            f"Across {len(values)} periods, {series_measure} peaked in {highest[0]} at "
            f"{highest[1]:,.2f} and was lowest in {lowest[0]} at {lowest[1]:,.2f}."
        )

    if result.rows:
        dimension = next(
            (column.name for column in result.columns if column.role == "dimension"), None
        )
        measure = next(
            (column.name for column in result.columns if column.role == "measure"), None
        )
        if dimension and measure:
            top = result.rows[0]
            text = f"{top.get(dimension)} leads with {top.get(measure):,.2f}"
            if len(result.rows) > 1:
                second = result.rows[1]
                text += f", followed by {second.get(dimension)} at {second.get(measure):,.2f}"
            return text + f". {result.row_count} group(s) returned."

    return f"{result.row_count} row(s) returned."
