"""Resolve dashboard widgets against a loaded frame.

Every widget here is a thin adapter onto a service that already exists: a KPI
widget calls ``analytics_service.evaluate_kpi``, a chart widget calls
``dataset_charts.build_chart``, a table widget calls ``dataset_query.aggregate``,
an insight widget reads a stored ``InsightRun``. This module contains no
statistics of its own - if a figure appears on a dashboard, some other module
computed it.

Two design rules matter:

1. **The frame is loaded once.** Resolution takes an already-loaded DataFrame,
   so a dashboard of twenty widgets reads the dataset file once, not twenty
   times. Shared derived state (the insight report, the semantic model) is
   memoised on the context for the same reason.
2. **A widget fails alone.** ``resolve`` never raises for a bad widget - it
   returns a ``WidgetResult`` carrying a safe message, so nineteen working
   widgets still render when the twentieth is misconfigured.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from app.core.exceptions import AppError, ValidationError
from app.core.logging import get_logger
from app.models.dashboard import DashboardWidget, WidgetType
from app.schemas.advanced_analytics import ForecastMethod
from app.schemas.analytics import MetricType, SegmentRequest, TimeSeriesRequest
from app.schemas.dashboard import (
    AdvancedAnalysis,
    AdvancedWidgetConfig,
    AdvancedWidgetData,
    AiInsightWidgetConfig,
    ChartWidgetConfig,
    InsightWidgetData,
    KpiWidgetConfig,
    KpiWidgetData,
    NlqWidgetConfig,
    NlqWidgetData,
    RecommendationWidgetConfig,
    RecommendationWidgetData,
    TableWidgetConfig,
    TableWidgetData,
    TextWidgetConfig,
    TextWidgetData,
    WidgetConfig,
    WidgetPosition,
    WidgetResult,
    WidgetStatus,
)
from app.schemas.insights import InsightReport
from app.schemas.visualization import (
    AggregationSpec,
    ChartConfig,
    ChartDataResponse,
    ChartSeries,
    ChartType,
    FilterCondition,
    FilterLogic,
    FilterSet,
)
from app.services import (
    advanced_analytics_engine as advanced_engine,
)
from app.services import (
    analytics_engine,
    analytics_service,
    dataset_charts,
    dataset_query,
    nlq_executor,
    nlq_planner,
    semantic_columns,
)
from app.services.semantic_columns import SemanticModel

logger = get_logger(__name__)

#: Rows returned by an advanced-analytics widget before it is truncated.
ADVANCED_ROW_LIMIT = 25

_GENERIC_ERROR = "Unable to load this widget."


def _data(**payload: Any) -> dict[str, Any]:
    """A resolver's output: exactly one populated field of ``WidgetResult``."""
    return payload


def merge_filters(*sets: FilterSet | None) -> FilterSet | None:
    """Combine dashboard and widget filters into one AND-ed set.

    Dashboard filters narrow every compatible widget, so they are appended to
    whatever the widget already carries rather than replacing it.
    """
    conditions: list[FilterCondition] = []
    for item in sets:
        if item is not None:
            conditions.extend(item.conditions)
    if not conditions:
        return None
    return FilterSet(logic=FilterLogic.AND, conditions=conditions)


@dataclass
class WidgetContext:
    """Everything shared across one dashboard refresh.

    The expensive pieces - the frame, the analyst report, the insight run - are
    computed at most once per refresh and reused by every widget that needs
    them.
    """

    frame: pd.DataFrame
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None
    #: Dashboard-level filters, already merged from saved and ad-hoc sources.
    dashboard_filters: FilterSet | None = None
    #: Supplied by the service; resolving an insight widget needs a DB read,
    #: so the run is fetched once before resolution begins.
    insights: InsightReport | None = None
    insight_run_id: uuid.UUID | None = None
    insight_generated_at: datetime | None = None
    insight_stale: bool = False
    #: Recorded NLQ plans, keyed by id, pre-loaded for the same reason.
    nlq_plans: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)

    _model: SemanticModel | None = None

    @property
    def model(self) -> SemanticModel:
        if self._model is None:
            self._model = semantic_columns.detect(self.frame)
        return self._model

    def filtered(self, widget_filters: FilterSet | None) -> pd.DataFrame:
        """The frame narrowed by the dashboard's filters and the widget's own."""
        combined = merge_filters(self.dashboard_filters, widget_filters)
        return dataset_query.apply_filters(self.frame, combined)


# --- Individual widgets ------------------------------------------------------


def _resolve_kpi(config: KpiWidgetConfig, context: WidgetContext) -> dict[str, Any]:
    """Straight through to the existing KPI evaluator."""
    definition = config.definition.model_copy(
        update={"filters": merge_filters(context.dashboard_filters, config.definition.filters)}
    )
    return _data(
        kpi=KpiWidgetData(result=analytics_service.evaluate_kpi(context.frame, definition))
    )


def _time_series_chart(
    config: ChartWidgetConfig, frame: pd.DataFrame
) -> ChartDataResponse:
    """A date-bucketed chart, built on the existing time-series engine.

    ``dataset_charts`` groups by distinct category value, which is right for a
    dimension and wrong for a date - it would produce one point per timestamp.
    When the widget names a granularity, the aggregation goes through
    ``analytics_engine`` instead, which is the same code the analytics page
    uses.
    """
    if config.x_column is None or config.period is None:
        raise ValidationError("A date column and a granularity are required.")

    metric = MetricType(config.aggregation.value)
    series = analytics_engine.build_time_series(
        frame,
        TimeSeriesRequest(
            date_column=config.x_column,
            period=config.period,
            metric=metric,
            column=config.y_column,
            group_by=config.group_by,
            max_points=500,
        ),
    )
    label = config.y_axis_label or config.y_column or "count"
    return ChartDataResponse(
        chart_type=config.chart_type,
        x_axis=config.x_axis_label or config.x_column,
        y_axis=label,
        labels=series.labels,
        series=[
            ChartSeries(name=item.name, data=[point.value for point in item.points])
            for item in series.series
        ],
        metadata={"period": config.period.value, "aggregation": config.aggregation.value},
    )


def _resolve_chart(config: ChartWidgetConfig, context: WidgetContext) -> dict[str, Any]:
    frame = context.filtered(config.filters)
    if frame.empty:
        raise ValidationError("No rows match the selected filters.")

    if config.period is not None:
        return _data(chart=_time_series_chart(config, frame))

    chart = dataset_charts.build_chart(
        frame,
        ChartConfig(
            chart_type=config.chart_type,
            x_column=config.x_column,
            y_column=config.y_column,
            group_by=config.group_by,
            aggregation=config.aggregation,
            # Filters are already applied above, so they are not passed again.
            filters=None,
            x_axis_label=config.x_axis_label,
            y_axis_label=config.y_axis_label,
            bins=config.bins,
            max_categories=config.max_categories,
        ),
    )
    return _data(chart=chart)


def _resolve_table(config: TableWidgetConfig, context: WidgetContext) -> dict[str, Any]:
    frame = context.filtered(config.filters)
    if frame.empty:
        raise ValidationError("No rows match the selected filters.")

    if config.aggregations:
        result = dataset_query.aggregate(
            frame,
            config.group_by,
            [
                AggregationSpec(
                    column=item.column, aggregation=item.aggregation, alias=item.alias
                )
                for item in config.aggregations
            ],
        )
    else:
        columns = config.columns or [str(name) for name in frame.columns][:10]
        for column in columns:
            dataset_query.require_column(frame, column)
        result = frame[columns]

    if config.sort_by:
        if config.sort_by not in result.columns:
            raise ValidationError(f"Cannot sort by '{config.sort_by}': it is not in the result.")
        result = result.sort_values(config.sort_by, ascending=not config.sort_desc)

    total = int(len(result))
    trimmed = result.head(config.limit)

    return _data(
        table=TableWidgetData(
            columns=[str(name) for name in trimmed.columns],
            rows=dataset_query.rows_to_records(trimmed),
            row_count=total,
            truncated=total > config.limit,
        )
    )


def _resolve_insight(config: AiInsightWidgetConfig, context: WidgetContext) -> dict[str, Any]:
    """Reads an existing insight run. Never generates a second one."""
    if context.insights is None:
        raise ValidationError(
            "No AI insights have been generated for this dataset yet. "
            "Generate them on the AI insights page first."
        )

    insights = list(context.insights.insights)
    if config.insight_ids:
        wanted = set(config.insight_ids)
        insights = [item for item in insights if item.id in wanted]
    if config.categories:
        allowed = set(config.categories)
        insights = [item for item in insights if item.category.value in allowed]
    if config.priorities:
        allowed = set(config.priorities)
        insights = [item for item in insights if item.priority.value in allowed]

    health = context.insights.health
    return _data(
        insight=InsightWidgetData(
            insights=insights[: config.limit],
            health_score=health.score if config.show_health else None,
            health_rating=health.rating.value if config.show_health else None,
            run_id=context.insight_run_id,
            generated_at=context.insight_generated_at,
            stale=context.insight_stale,
        )
    )


def _resolve_recommendation(
    config: RecommendationWidgetConfig, context: WidgetContext
) -> dict[str, Any]:
    if context.insights is None:
        raise ValidationError(
            "No AI insights have been generated for this dataset yet. "
            "Generate them on the AI insights page first."
        )

    recommendations = list(context.insights.recommendations)
    if config.priorities:
        allowed = set(config.priorities)
        recommendations = [item for item in recommendations if item.priority.value in allowed]

    return _data(
        recommendation=RecommendationWidgetData(
            recommendations=recommendations[: config.limit],
            run_id=context.insight_run_id,
            generated_at=context.insight_generated_at,
        )
    )


def _resolve_text(config: TextWidgetConfig, _context: WidgetContext) -> dict[str, Any]:
    return _data(text=TextWidgetData(content=config.content))


def _resolve_nlq(config: NlqWidgetConfig, context: WidgetContext) -> dict[str, Any]:
    """Replay a recorded query plan, re-validated against the current frame."""
    record = context.nlq_plans.get(config.nlq_query_id)
    if record is None:
        raise ValidationError(
            "The saved question this widget refers to is no longer available."
        )
    if not record.get("plan"):
        raise ValidationError("The saved question has no executable plan.")

    from app.schemas.nlq import QueryPlan

    # Re-validated every time: a plan that no longer fits the data must fail
    # rather than run against the wrong columns.
    plan = nlq_planner.validate_plan(context.frame, QueryPlan.model_validate(record["plan"]))
    result = nlq_executor.execute(context.filtered(None), plan)

    chart = None
    if config.show_chart:
        recommendation = nlq_executor.recommend_chart(plan, result)
        if recommendation is not None and result.rows:
            chart = _chart_from_rows(result.rows, recommendation.chart_type, plan)

    return _data(
        nlq=NlqWidgetData(
            question=str(record.get("question", "")),
            answer=nlq_executor.describe_answer(str(record.get("question", "")), plan, result),
            columns=[column.name for column in result.columns],
            rows=result.rows,
            metric_label=result.metric_label,
            metric_value=result.metric_value,
            chart=chart,
        )
    )


def _chart_from_rows(
    rows: list[dict[str, Any]], chart_type: ChartType, plan: Any
) -> ChartDataResponse | None:
    """Turn an NLQ result's rows into the platform's chart shape."""
    if not rows:
        return None
    keys = list(rows[0])
    if len(keys) < 2:
        return None

    label_key, value_key = keys[0], keys[-1]
    values: list[float | None] = []
    for row in rows:
        raw = row.get(value_key)
        values.append(float(raw) if isinstance(raw, (int, float)) else None)

    return ChartDataResponse(
        chart_type=chart_type,
        x_axis=label_key,
        y_axis=value_key,
        labels=[str(row.get(label_key)) for row in rows],
        series=[ChartSeries(name=str(value_key), data=values)],
        metadata={"source": "nlq", "intent": getattr(plan.intent, "value", str(plan.intent))},
    )


# --- Advanced analytics ------------------------------------------------------


def _require_role(model: SemanticModel, role: str, override: str | None, analysis: str) -> str:
    column = override or model.get(role)
    if not column:
        raise ValidationError(
            f"{analysis} needs a {role} column, which was not detected in this dataset."
        )
    return column


def _resolve_advanced(config: AdvancedWidgetConfig, context: WidgetContext) -> dict[str, Any]:
    """Embed one advanced analysis, using the existing engines unchanged."""
    frame = context.filtered(config.filters)
    if frame.empty:
        raise ValidationError("No rows match the selected filters.")

    model = context.model
    name = config.analysis.value.upper()

    match config.analysis:
        case AdvancedAnalysis.RFM:
            customer = _require_role(model, "customer", config.dimension, name)
            date = _require_role(model, "date", None, name)
            revenue = _require_role(model, "revenue", config.column, name)
            segments, _customers, ctx = advanced_engine.build_rfm(
                frame, customer, date, revenue
            )
            return _data(
                advanced=AdvancedWidgetData(
                    analysis=config.analysis,
                    metrics=[
                        {"label": "Customers", "value": ctx["customer_count"]},
                        {"label": f"Total {revenue}", "value": ctx["total_monetary"]},
                    ],
                    columns=["Segment", "Customers", "% of customers", "Value"],
                    rows=[
                        {
                            "Segment": item.segment.value.replace("_", " ").title(),
                            "Customers": item.customer_count,
                            "% of customers": item.percentage,
                            "Value": item.total_monetary,
                        }
                        for item in segments[:ADVANCED_ROW_LIMIT]
                    ],
                    chart=ChartDataResponse(
                        chart_type=ChartType.BAR,
                        x_axis="segment",
                        y_axis="customers",
                        labels=[item.segment.value.replace("_", " ") for item in segments],
                        series=[
                            ChartSeries(
                                name="customers",
                                data=[float(item.customer_count) for item in segments],
                            )
                        ],
                    ),
                )
            )

        case AdvancedAnalysis.CHURN:
            customer = _require_role(model, "customer", config.dimension, name)
            date = _require_role(model, "date", None, name)
            result = advanced_engine.build_churn(
                frame, customer, date, model.get("revenue"), 90, 45, config.limit
            )
            return _data(
                advanced=AdvancedWidgetData(
                    analysis=config.analysis,
                    metrics=[
                        {"label": "Active", "value": result["active_customers"]},
                        {"label": "At risk", "value": result["at_risk_customers"]},
                        {"label": "Churned", "value": result["churned_customers"]},
                        {"label": "Churn rate", "value": result["churn_rate"], "suffix": "%"},
                    ],
                    columns=["Customer", "Last activity", "Days inactive", "Status"],
                    # build_churn returns plain dicts, not models.
                    rows=[
                        {
                            "Customer": item["customer"],
                            "Last activity": item["last_activity"],
                            "Days inactive": item["days_since_activity"],
                            "Status": str(item["status"]).replace("_", " "),
                        }
                        for item in result["customers"][:ADVANCED_ROW_LIMIT]
                    ],
                    note=(
                        "Rule-based: customers are classified by days since their last "
                        "recorded activity. No model is trained."
                    ),
                )
            )

        case AdvancedAnalysis.COHORT:
            customer = _require_role(model, "customer", config.dimension, name)
            date = _require_role(model, "date", None, name)
            rows, labels, averages = advanced_engine.build_cohort(
                frame, customer, date, config.period, 12
            )
            return _data(
                advanced=AdvancedWidgetData(
                    analysis=config.analysis,
                    metrics=[
                        {
                            "label": "Month 1 retention",
                            "value": averages[1] if len(averages) > 1 else None,
                            "suffix": "%",
                        },
                        {"label": "Cohorts", "value": len(rows)},
                    ],
                    columns=["Cohort", "Size", *labels],
                    rows=[
                        {
                            "Cohort": row.cohort,
                            "Size": row.cohort_size,
                            **{
                                label: row.percentages[index]
                                if index < len(row.percentages)
                                else None
                                for index, label in enumerate(labels)
                            },
                        }
                        for row in rows[:ADVANCED_ROW_LIMIT]
                    ],
                )
            )

        case AdvancedAnalysis.FORECAST:
            date = _require_role(model, "date", None, name)
            metric_column = config.column or model.get("revenue")
            series = analytics_engine.build_time_series(
                frame,
                TimeSeriesRequest(
                    date_column=date,
                    period=config.period,
                    metric=config.metric,
                    column=metric_column,
                    max_points=500,
                ),
            )
            points = [
                point
                for point in (series.series[0].points if series.series else [])
                if point.value is not None
            ]
            history, projection, ctx = advanced_engine.build_forecast(
                [point.label for point in points],
                [float(point.value or 0) for point in points],
                ForecastMethod.HOLT,
                config.horizon,
                config.period,
            )
            labels = [point.period for point in history] + [
                point.period for point in projection
            ]
            return _data(
                advanced=AdvancedWidgetData(
                    analysis=config.analysis,
                    metrics=[
                        {"label": "Trend", "value": ctx["trend"]},
                        {"label": "Periods observed", "value": ctx["periods_observed"]},
                        {"label": "Mean absolute error", "value": ctx["mean_absolute_error"]},
                    ],
                    columns=["Period", "Forecast", "Lower", "Upper"],
                    rows=[
                        {
                            "Period": point.period,
                            "Forecast": point.value,
                            "Lower": point.lower_bound,
                            "Upper": point.upper_bound,
                        }
                        for point in projection
                    ],
                    chart=ChartDataResponse(
                        chart_type=ChartType.LINE,
                        x_axis="period",
                        y_axis=metric_column or "value",
                        labels=labels,
                        series=[
                            ChartSeries(
                                name="history",
                                data=[point.value for point in history]
                                + [None] * len(projection),
                            ),
                            ChartSeries(
                                name="forecast",
                                data=[None] * len(history)
                                + [point.value for point in projection],
                            ),
                        ],
                    ),
                    note=(
                        "Intervals come from the model's own residuals and widen with "
                        "distance; they are not a guarantee."
                    ),
                )
            )

        case AdvancedAnalysis.PARETO:
            dimension = _require_role(model, "product", config.dimension, name)
            revenue = _require_role(model, "revenue", config.column, name)
            contribution = analytics_engine.build_contribution(
                frame,
                SegmentRequest(
                    dimension=dimension, metric=config.metric, column=revenue, limit=50
                ),
            )
            pareto_rows, vital_few = advanced_engine.pareto_from_contribution(
                contribution, 80.0
            )
            return _data(
                advanced=AdvancedWidgetData(
                    analysis=config.analysis,
                    metrics=[
                        {"label": "Vital few", "value": vital_few},
                        {"label": "Groups", "value": contribution.group_count},
                        {"label": f"Total {revenue}", "value": contribution.total},
                    ],
                    columns=["Item", "Value", "% of total", "Cumulative %"],
                    rows=[
                        {
                            "Item": row.label,
                            "Value": row.value,
                            "% of total": row.percentage,
                            "Cumulative %": row.cumulative_percentage,
                        }
                        for row in pareto_rows[:ADVANCED_ROW_LIMIT]
                    ],
                    chart=ChartDataResponse(
                        chart_type=ChartType.BAR,
                        x_axis=dimension,
                        y_axis=revenue,
                        labels=[row.label for row in pareto_rows[:ADVANCED_ROW_LIMIT]],
                        series=[
                            ChartSeries(
                                name=revenue,
                                data=[row.value for row in pareto_rows[:ADVANCED_ROW_LIMIT]],
                            )
                        ],
                    ),
                )
            )

        case AdvancedAnalysis.SEGMENTATION:
            features = [column.name for column in model.measures][:5]
            if len(features) < 2:
                raise ValidationError(
                    "Clustering needs at least two numeric measures; this dataset has fewer."
                )
            profiles, _points, ctx = advanced_engine.build_segmentation(
                frame, features, config.clusters, True, None, 1
            )
            return _data(
                advanced=AdvancedWidgetData(
                    analysis=config.analysis,
                    metrics=[
                        {"label": "Clusters", "value": len(profiles)},
                        {
                            "label": "Variance explained",
                            "value": round((ctx["explained_variance"] or 0) * 100, 1),
                            "suffix": "%",
                        },
                    ],
                    columns=["Cluster", "Size", "% of rows"],
                    rows=[
                        {
                            "Cluster": f"Cluster {item.cluster}",
                            "Size": item.size,
                            "% of rows": item.percentage,
                        }
                        for item in profiles
                    ],
                    chart=ChartDataResponse(
                        chart_type=ChartType.BAR,
                        x_axis="cluster",
                        y_axis="records",
                        labels=[f"Cluster {item.cluster}" for item in profiles],
                        series=[
                            ChartSeries(
                                name="records", data=[float(item.size) for item in profiles]
                            )
                        ],
                    ),
                    note=(
                        "K-Means with a fixed seed, so the same data always yields the "
                        "same clusters."
                    ),
                )
            )

    raise ValidationError(f"Unsupported analysis '{config.analysis}'.")


# --- Dispatch ----------------------------------------------------------------

_RESOLVERS: dict[WidgetType, Any] = {
    WidgetType.KPI: _resolve_kpi,
    WidgetType.CHART: _resolve_chart,
    WidgetType.TABLE: _resolve_table,
    WidgetType.AI_INSIGHT: _resolve_insight,
    WidgetType.RECOMMENDATION: _resolve_recommendation,
    WidgetType.TEXT: _resolve_text,
    WidgetType.NLQ_RESULT: _resolve_nlq,
    WidgetType.ADVANCED: _resolve_advanced,
}


def parse_config(widget: DashboardWidget) -> WidgetConfig:
    """Validate a stored configuration back into its typed model."""
    from pydantic import TypeAdapter

    adapter: TypeAdapter[WidgetConfig] = TypeAdapter(WidgetConfig)
    return adapter.validate_python(widget.configuration)


def resolve(widget: DashboardWidget, context: WidgetContext) -> WidgetResult:
    """Resolve one widget, never raising.

    An expected failure (a missing column, an empty filter result) surfaces its
    own message; anything unexpected is logged and reported generically, so an
    internal error can never leak through a dashboard.
    """
    position = WidgetPosition(
        x=widget.position_x, y=widget.position_y, width=widget.width, height=widget.height
    )
    base = {
        "widget_id": widget.id,
        "widget_type": widget.widget_type,
        "title": widget.title,
        "position": position,
    }

    try:
        config = parse_config(widget)
        resolver = _RESOLVERS[widget.widget_type]
        payload = resolver(config, context)
    except AppError as exc:
        return WidgetResult(**base, status=WidgetStatus.ERROR, error=exc.message)
    except Exception:
        logger.exception("Dashboard widget %s could not be resolved", widget.id)
        return WidgetResult(**base, status=WidgetStatus.ERROR, error=_GENERIC_ERROR)

    return WidgetResult(**base, **payload)


__all__ = ["WidgetContext", "merge_filters", "parse_config", "resolve"]
