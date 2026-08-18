"""Deterministic business insights.

Everything here is computed from the data before any LLM is involved, and
reuses the existing analytics services rather than reimplementing them:
KPIs and segmentation come from ``analytics_engine``, outliers from
``dataset_cleaning``, quality from ``data_quality``.

Guarantees:
- A metric is only produced when the columns it needs actually exist.
- Trends are not called on too few observations.
- Outliers are reported as *potential* anomalies, never asserted as errors.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.schemas.ai_analyst import (
    AnalystKpi,
    AnomalyFinding,
    DataQualityNote,
    Insight,
    InsightCategory,
    InsightSeverity,
    SegmentFinding,
    TrendDirection,
    TrendFinding,
)
from app.schemas.analytics import (
    AbcRequest,
    GrowthRequest,
    MetricType,
    SegmentRequest,
    TimePeriod,
)
from app.schemas.cleaning import OutlierMethod
from app.schemas.profiling import DataQualitySummary
from app.services import analytics_engine, dataset_cleaning
from app.services.semantic_columns import SemanticModel

logger = get_logger(__name__)

#: A trend needs at least this many periods before a direction is stated.
MIN_TREND_PERIODS = 3
#: Below this absolute percentage change a trend is called stable.
STABLE_BAND_PCT = 5.0
#: Segment concentration at or above this share is worth flagging.
HIGH_CONCENTRATION_PCT = 50.0
#: Outlier share above this is raised from info to a medium finding.
NOTABLE_OUTLIER_PCT = 1.0
#: Correlation strength at or above this is worth mentioning.
NOTABLE_CORRELATION = 0.3
#: Rows needed before a correlation is reported at all.
MIN_CORRELATION_ROWS = 30


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return round(value, digits)


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return _round(((current - (previous or 0)) / (previous or 1)) * 100)


def _metric(frame: pd.DataFrame, metric: MetricType, column: str | None) -> float | None:
    """Compute a metric, swallowing expected failures into None."""
    try:
        return analytics_engine.compute_metric(frame, metric, column)
    except AppError:
        return None


# --- KPIs --------------------------------------------------------------------


def build_kpis(frame: pd.DataFrame, model: SemanticModel) -> list[AnalystKpi]:
    """Headline figures for whichever business roles the dataset supports."""
    kpis: list[AnalystKpi] = [
        AnalystKpi(
            name="Total records",
            metric="count",
            value=float(len(frame)),
        )
    ]

    for role, metric, label in (
        ("revenue", MetricType.SUM, "Total {column}"),
        ("revenue", MetricType.AVERAGE, "Average {column}"),
        ("quantity", MetricType.SUM, "Total {column}"),
        ("quantity", MetricType.AVERAGE, "Average {column}"),
        ("discount", MetricType.AVERAGE, "Average {column}"),
        ("rating", MetricType.AVERAGE, "Average {column}"),
        ("delivery", MetricType.AVERAGE, "Average {column}"),
        ("price", MetricType.AVERAGE, "Average {column}"),
        ("profit", MetricType.SUM, "Total {column}"),
    ):
        column = model.get(role)
        if column is None:
            continue
        value = _metric(frame, metric, column)
        kpis.append(
            AnalystKpi(
                name=label.format(column=column),
                metric=metric.value,
                column=column,
                value=_round(value),
                available=value is not None,
                reason=None if value is not None else "No usable values in this column.",
            )
        )

    for role in ("customer", "order", "product"):
        column = model.get(role)
        if column is None:
            continue
        value = _metric(frame, MetricType.DISTINCT_COUNT, column)
        kpis.append(
            AnalystKpi(
                name=f"Unique {column}",
                metric="distinct_count",
                column=column,
                value=_round(value, 0),
                available=value is not None,
            )
        )

    # Average value per entity, only when both halves of the ratio exist.
    revenue, entity = model.get("revenue"), model.get("order") or model.get("customer")
    if revenue and entity:
        total = _metric(frame, MetricType.SUM, revenue)
        entities = _metric(frame, MetricType.DISTINCT_COUNT, entity)
        value = _round(total / entities) if total is not None and entities else None
        kpis.append(
            AnalystKpi(
                name=f"Average {revenue} per {entity}",
                metric="ratio",
                column=revenue,
                value=value,
                available=value is not None,
                reason=None if value is not None else "Not enough data to form the ratio.",
            )
        )

    return kpis


def kpi_insights(kpis: list[AnalystKpi], model: SemanticModel) -> list[Insight]:
    insights: list[Insight] = []
    for index, kpi in enumerate(kpis):
        if not kpi.available or kpi.value is None:
            continue
        insights.append(
            Insight(
                id=f"kpi-{index}",
                category=InsightCategory.KPI,
                title=kpi.name,
                summary=f"{kpi.name} is {kpi.value:,.2f}.",
                metric=kpi.metric,
                value=kpi.value,
                dimension=kpi.column,
                severity=InsightSeverity.INFO,
                supporting_data={"column": kpi.column, "metric": kpi.metric},
            )
        )
    return insights


# --- Trends ------------------------------------------------------------------


def _choose_period(frame: pd.DataFrame, date_column: str) -> TimePeriod:
    """Pick a granularity that yields a readable number of periods."""
    try:
        dates = analytics_engine.parse_dates(frame, date_column).dropna()
    except AppError:
        return TimePeriod.MONTH
    if dates.empty:
        return TimePeriod.MONTH

    span_days = (dates.max() - dates.min()).days
    if span_days <= 31:
        return TimePeriod.DAY
    if span_days <= 120:
        return TimePeriod.WEEK
    if span_days <= 1095:
        return TimePeriod.MONTH
    return TimePeriod.QUARTER


def build_trends(frame: pd.DataFrame, model: SemanticModel) -> list[TrendFinding]:
    """Trend per measure against the dataset's time axis, when one exists."""
    date_column = model.get("date")
    if date_column is None:
        return []

    period = _choose_period(frame, date_column)
    findings: list[TrendFinding] = []

    # Only the roles a business actually trends, and only if present.
    candidates = [
        model.get(role) for role in ("revenue", "quantity", "profit", "rating", "delivery")
    ]
    for column in [name for name in dict.fromkeys(candidates) if name]:
        try:
            growth = analytics_engine.build_growth(
                frame,
                GrowthRequest(
                    date_column=date_column,
                    period=period,
                    metric=MetricType.SUM
                    if column in (model.get("revenue"), model.get("quantity"), model.get("profit"))
                    else MetricType.AVERAGE,
                    column=column,
                ),
            )
        except AppError as exc:
            logger.info("Trend skipped for %s: %s", column, exc.message)
            continue

        points = [point for point in growth.points if point.value is not None]
        if len(points) < MIN_TREND_PERIODS:
            findings.append(
                TrendFinding(
                    metric_column=column,
                    date_column=date_column,
                    period=period,
                    direction=TrendDirection.INSUFFICIENT_DATA,
                    periods_observed=len(points),
                    note=(
                        f"Only {len(points)} {period.value} period(s) of data - "
                        f"at least {MIN_TREND_PERIODS} are needed to describe a trend."
                    ),
                )
            )
            continue

        first, last = points[0], points[-1]
        change = _pct_change(last.value, first.value)
        if change is None:
            direction = TrendDirection.STABLE
        elif change > STABLE_BAND_PCT:
            direction = TrendDirection.INCREASING
        elif change < -STABLE_BAND_PCT:
            direction = TrendDirection.DECREASING
        else:
            direction = TrendDirection.STABLE

        highest = max(points, key=lambda point: point.value or 0)
        lowest = min(points, key=lambda point: point.value or 0)

        findings.append(
            TrendFinding(
                metric_column=column,
                date_column=date_column,
                period=period,
                direction=direction,
                first_label=first.label,
                last_label=last.label,
                first_value=_round(first.value),
                last_value=_round(last.value),
                percentage_change=change,
                highest_label=highest.label,
                highest_value=_round(highest.value),
                lowest_label=lowest.label,
                lowest_value=_round(lowest.value),
                periods_observed=len(points),
            )
        )

    return findings


def trend_insights(trends: list[TrendFinding]) -> list[Insight]:
    insights: list[Insight] = []
    for index, trend in enumerate(trends):
        if trend.direction is TrendDirection.INSUFFICIENT_DATA:
            insights.append(
                Insight(
                    id=f"trend-{index}",
                    category=InsightCategory.TREND,
                    title=f"Not enough history for {trend.metric_column}",
                    summary=trend.note or "Insufficient data to describe a trend.",
                    metric="trend",
                    dimension=trend.metric_column,
                    severity=InsightSeverity.INFO,
                    supporting_data={"periods_observed": trend.periods_observed},
                )
            )
            continue

        severity = (
            InsightSeverity.HIGH
            if trend.direction is TrendDirection.DECREASING
            and (trend.percentage_change or 0) <= -20
            else InsightSeverity.MEDIUM
            if trend.direction is not TrendDirection.STABLE
            else InsightSeverity.INFO
        )
        change_text = (
            f"{trend.percentage_change:+.1f}%" if trend.percentage_change is not None else "n/a"
        )
        recommendation = None
        if trend.direction is TrendDirection.DECREASING:
            recommendation = (
                f"Investigate the decline in {trend.metric_column} between "
                f"{trend.first_label} and {trend.last_label}."
            )

        insights.append(
            Insight(
                id=f"trend-{index}",
                category=InsightCategory.TREND,
                title=f"{trend.metric_column} is {trend.direction.value}",
                summary=(
                    f"{trend.metric_column} moved {change_text} from {trend.first_label} "
                    f"({trend.first_value:,.2f}) to {trend.last_label} "
                    f"({trend.last_value:,.2f}) by {trend.period.value}. Highest: "
                    f"{trend.highest_label} ({trend.highest_value:,.2f}); lowest: "
                    f"{trend.lowest_label} ({trend.lowest_value:,.2f})."
                ),
                metric="trend",
                value=trend.last_value,
                comparison_value=trend.first_value,
                percentage_change=trend.percentage_change,
                dimension=trend.metric_column,
                severity=severity,
                supporting_data={
                    "period": trend.period.value,
                    "periods_observed": trend.periods_observed,
                    "highest": {"label": trend.highest_label, "value": trend.highest_value},
                    "lowest": {"label": trend.lowest_label, "value": trend.lowest_value},
                },
                recommendation=recommendation,
            )
        )
    return insights


# --- Anomalies ---------------------------------------------------------------


def build_anomalies(frame: pd.DataFrame, model: SemanticModel) -> list[AnomalyFinding]:
    """IQR-based outlier detection over the dataset's measures."""
    findings: list[AnomalyFinding] = []
    row_count = len(frame)
    if row_count < 4:
        return findings

    for role in ("revenue", "quantity", "discount", "rating", "delivery", "price", "profit"):
        column = model.get(role)
        if column is None:
            continue

        values = pd.to_numeric(frame[column], errors="coerce")
        if values.dropna().nunique() <= 1:
            continue

        mask = dataset_cleaning.outlier_mask(values, OutlierMethod.IQR, 1.5)
        count = int(mask.sum())
        if count == 0:
            continue

        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        outliers = values[mask].dropna()

        context: dict[str, Any] = {}
        # Where do the outliers concentrate? Only ask if there is a dimension.
        dimension = model.get("product") or model.get("region")
        if dimension and dimension in frame.columns:
            grouped = frame.loc[mask.fillna(False), dimension].astype(str).value_counts().head(3)
            context["top_segments"] = [
                {"value": str(index), "outliers": int(value)} for index, value in grouped.items()
            ]

        findings.append(
            AnomalyFinding(
                metric_column=column,
                method="iqr",
                outlier_count=count,
                outlier_percentage=_round((count / row_count) * 100) or 0.0,
                lower_bound=_round(float(q1 - 1.5 * iqr)),
                upper_bound=_round(float(q3 + 1.5 * iqr)),
                minimum_outlier=_round(float(outliers.min())),
                maximum_outlier=_round(float(outliers.max())),
                context=context,
                examples=[
                    {"value": _round(float(value))} for value in outliers.head(5).tolist()
                ],
            )
        )

    return findings


def anomaly_insights(anomalies: list[AnomalyFinding]) -> list[Insight]:
    insights: list[Insight] = []
    for index, anomaly in enumerate(anomalies):
        severity = (
            InsightSeverity.MEDIUM
            if anomaly.outlier_percentage >= NOTABLE_OUTLIER_PCT
            else InsightSeverity.LOW
        )
        insights.append(
            Insight(
                id=f"anomaly-{index}",
                category=InsightCategory.ANOMALY,
                title=f"Potential anomalies in {anomaly.metric_column}",
                # Deliberately hedged: an outlier is unusual, not proven wrong.
                summary=(
                    f"Potential anomaly detected: {anomaly.outlier_count} value(s) "
                    f"({anomaly.outlier_percentage:.2f}% of rows) in "
                    f"'{anomaly.metric_column}' fall outside the expected range "
                    f"{anomaly.lower_bound:,.2f} to {anomaly.upper_bound:,.2f} "
                    f"(IQR method). Observed extremes: {anomaly.minimum_outlier:,.2f} "
                    f"to {anomaly.maximum_outlier:,.2f}. These may be legitimate "
                    f"values and warrant review rather than correction."
                ),
                metric="outliers",
                value=float(anomaly.outlier_count),
                dimension=anomaly.metric_column,
                severity=severity,
                supporting_data={
                    "method": anomaly.method,
                    "bounds": [anomaly.lower_bound, anomaly.upper_bound],
                    "examples": anomaly.examples,
                    **anomaly.context,
                },
                recommendation=(
                    f"Review the extreme '{anomaly.metric_column}' values before using "
                    "them in reporting."
                ),
            )
        )
    return insights


# --- Segments ----------------------------------------------------------------


def build_segments(frame: pd.DataFrame, model: SemanticModel) -> list[SegmentFinding]:
    """Reuses the existing segmentation and ABC services."""
    value_column = model.get("revenue")
    metric = MetricType.SUM if value_column else MetricType.COUNT
    findings: list[SegmentFinding] = []

    dimensions = [
        model.get("product"),
        model.get("region"),
        model.get("channel"),
    ]
    for dimension in [name for name in dict.fromkeys(dimensions) if name]:
        try:
            top = analytics_engine.build_segment(
                frame,
                SegmentRequest(dimension=dimension, metric=metric, column=value_column, limit=5),
            )
            bottom = analytics_engine.build_segment(
                frame,
                SegmentRequest(
                    dimension=dimension,
                    metric=metric,
                    column=value_column,
                    sort="asc",  # type: ignore[arg-type]
                    limit=5,
                ),
            )
        except AppError as exc:
            logger.info("Segment skipped for %s: %s", dimension, exc.message)
            continue

        class_a_count: int | None = None
        if value_column:
            try:
                abc = analytics_engine.build_abc(
                    frame,
                    AbcRequest(dimension=dimension, metric=metric, column=value_column),
                )
                class_a_count = next(
                    (item.item_count for item in abc.summary if item.abc_class == "A"), None
                )
            except AppError:
                class_a_count = None

        top_share = top.rows[0].percentage if top.rows else None
        note = None
        if top_share is not None and top_share >= HIGH_CONCENTRATION_PCT:
            note = (
                f"'{top.rows[0].label}' alone accounts for {top_share:.1f}% of the total - "
                "a concentration risk."
            )

        findings.append(
            SegmentFinding(
                dimension=dimension,
                metric_column=value_column,
                metric=metric.value,
                total=_round(top.total),
                top=[
                    {"label": row.label, "value": _round(row.value), "percentage": row.percentage}
                    for row in top.rows
                ],
                bottom=[
                    {"label": row.label, "value": _round(row.value), "percentage": row.percentage}
                    for row in bottom.rows
                ],
                top_share_percentage=top_share,
                class_a_count=class_a_count,
                concentration_note=note,
            )
        )

    return findings


def segment_insights(segments: list[SegmentFinding]) -> list[Insight]:
    insights: list[Insight] = []
    for index, segment in enumerate(segments):
        if not segment.top:
            continue

        best = segment.top[0]
        worst = segment.bottom[0] if segment.bottom else None
        measure = segment.metric_column or "record count"

        insights.append(
            Insight(
                id=f"segment-{index}",
                category=InsightCategory.SEGMENT,
                title=f"{measure} by {segment.dimension}",
                summary=(
                    f"'{best['label']}' leads {segment.dimension} with "
                    f"{best['value']:,.2f}"
                    + (
                        f" ({best['percentage']:.1f}% of total)"
                        if best.get("percentage") is not None
                        else ""
                    )
                    + (
                        f". Lowest is '{worst['label']}' at {worst['value']:,.2f}."
                        if worst
                        else "."
                    )
                ),
                metric=segment.metric,
                value=best.get("value"),
                dimension=segment.dimension,
                dimension_value=str(best["label"]),
                severity=(
                    InsightSeverity.MEDIUM
                    if segment.top_share_percentage
                    and segment.top_share_percentage >= HIGH_CONCENTRATION_PCT
                    else InsightSeverity.INFO
                ),
                # Share of the metric is a measurable confidence, not a guess.
                confidence=(
                    round(best["percentage"] / 100, 4)
                    if best.get("percentage") is not None
                    else None
                ),
                supporting_data={
                    "top": segment.top,
                    "bottom": segment.bottom,
                    "class_a_count": segment.class_a_count,
                },
                recommendation=(
                    segment.concentration_note
                    and f"{segment.concentration_note} Consider diversifying."
                )
                or (
                    f"Focus on '{best['label']}' and review why '{worst['label']}' "
                    f"underperforms."
                    if worst
                    else None
                ),
            )
        )

        if segment.concentration_note:
            insights.append(
                Insight(
                    id=f"segment-{index}-concentration",
                    category=InsightCategory.SEGMENT,
                    title=f"Concentration in {segment.dimension}",
                    summary=segment.concentration_note,
                    metric="concentration",
                    value=segment.top_share_percentage,
                    dimension=segment.dimension,
                    dimension_value=str(best["label"]),
                    severity=InsightSeverity.HIGH,
                    supporting_data={"class_a_count": segment.class_a_count},
                    recommendation=(
                        "Reduce dependence on a single "
                        f"{segment.dimension} by growing other groups."
                    ),
                )
            )

    return insights


# --- Relationships -----------------------------------------------------------


def relationship_insights(frame: pd.DataFrame, model: SemanticModel) -> list[Insight]:
    """Correlations that a business would actually ask about.

    Only reported when there are enough rows and the relationship is not
    negligible - and always described as an association, not a cause.
    """
    revenue = model.get("revenue")
    if revenue is None or len(frame) < MIN_CORRELATION_ROWS:
        return []

    insights: list[Insight] = []
    for role in ("discount", "rating", "delivery", "quantity", "price"):
        column = model.get(role)
        if column is None or column == revenue:
            continue

        pair = pd.DataFrame(
            {
                "x": pd.to_numeric(frame[column], errors="coerce"),
                "y": pd.to_numeric(frame[revenue], errors="coerce"),
            }
        ).dropna()
        if len(pair) < MIN_CORRELATION_ROWS or pair["x"].nunique() <= 1:
            continue

        correlation = pair["x"].corr(pair["y"])
        if correlation is None or math.isnan(correlation):
            continue
        if abs(correlation) < NOTABLE_CORRELATION:
            continue

        direction = "higher" if correlation > 0 else "lower"
        insights.append(
            Insight(
                id=f"relationship-{role}",
                category=InsightCategory.KPI,
                title=f"{column} is associated with {revenue}",
                summary=(
                    f"Rows with higher '{column}' tend to show {direction} "
                    f"'{revenue}' (correlation {correlation:.2f} across "
                    f"{len(pair):,} rows). This is an association, not proof of cause."
                ),
                metric="correlation",
                value=_round(float(correlation)),
                dimension=column,
                severity=InsightSeverity.MEDIUM if abs(correlation) >= 0.5 else InsightSeverity.LOW,
                supporting_data={"rows": int(len(pair)), "against": revenue},
                recommendation=(
                    f"Test whether changing '{column}' moves '{revenue}' before acting."
                ),
            )
        )

    return insights


# --- Data quality ------------------------------------------------------------


def quality_notes(summary: DataQualitySummary) -> tuple[list[DataQualityNote], list[Insight]]:
    """Reuses the existing quality rules; no new detection logic."""
    notes = [
        DataQualityNote(
            issue_type=issue.issue_type.value,
            severity=issue.severity.value,
            column=issue.column,
            message=issue.message,
            affected_rows=issue.affected_rows,
        )
        for issue in summary.issues
    ]

    insights = [
        Insight(
            id=f"quality-{index}",
            category=InsightCategory.DATA_QUALITY,
            title=f"Data quality: {issue.issue_type.value.replace('_', ' ')}",
            summary=issue.message,
            metric="affected_rows",
            value=float(issue.affected_rows),
            dimension=issue.column,
            severity=(
                InsightSeverity.HIGH
                if issue.severity.value == "critical"
                else InsightSeverity.MEDIUM
                if issue.severity.value == "warning"
                else InsightSeverity.INFO
            ),
            supporting_data={"quality_status": summary.status.value, "score": summary.score},
            recommendation="Address this in the Cleaning step before relying on the figures.",
        )
        for index, issue in enumerate(summary.issues)
        if issue.severity.value in ("critical", "warning")
    ]

    return notes, insights
