"""Deterministic business-insight detection.

This runs *before* any LLM is involved and is the only place insights are
created. Every figure comes from an existing service - the analyst report
(KPIs, trends, anomalies, segments), ``analytics_engine`` for grouped
aggregation, ``advanced_analytics_engine`` for RFM and churn, ``data_quality``
for quality rules. Nothing is recalculated here that another module already
computed.

Three rules run through the whole module:

1. A detector returns nothing unless the roles it needs are actually present.
   No insight is ever produced from an assumed column name.
2. Wording is hedged where the evidence is. A correlation is described as an
   association, an outlier as a candidate for review, a decline as a potential
   risk - never as a proven cause.
3. Every insight carries the figures behind it, so the UI can answer "why am I
   seeing this?" without recomputing anything.

It is pure and synchronous: no I/O, no database, no AI.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.schemas.advanced_analytics import RfmSegmentSummary
from app.schemas.ai_analyst import AnalystReport, TrendDirection, TrendFinding
from app.schemas.analytics import (
    MetricType,
    SegmentRequest,
    TimePeriod,
    TimeSeriesRequest,
)
from app.schemas.insights import (
    BusinessInsight,
    Evidence,
    InsightCategory,
    InsightPriority,
    InsightSeverity,
    Recommendation,
)
from app.schemas.profiling import DataQualitySummary
from app.services import advanced_analytics_engine as advanced_engine
from app.services import analytics_engine, insight_engine
from app.services.semantic_columns import SemanticModel

logger = get_logger(__name__)

Category = InsightCategory
Severity = InsightSeverity
Priority = InsightPriority

#: Bumped whenever detection rules change, so stored runs can be marked stale.
ANALYSIS_VERSION = "1"

#: A change smaller than this is treated as flat rather than as movement.
MATERIAL_CHANGE_PCT = 5.0
#: A decline at or beyond this is a high-severity risk.
SHARP_DECLINE_PCT = -20.0
#: Growth at or beyond this is an opportunity worth naming.
STRONG_GROWTH_PCT = 20.0
#: One group holding at least this share of a measure is a concentration risk.
CONCENTRATION_PCT = 50.0
#: Minimum groups before "top" and "bottom" of a dimension mean anything.
MIN_GROUPS = 3
#: Minimum periods before a period-over-period comparison is offered.
MIN_PERIODS_FOR_COMPARISON = 2
#: Minimum periods before a sustained direction is claimed.
MIN_PERIODS_FOR_TREND = 4
#: Calendar months needed before a seasonal pattern is even considered.
MIN_MONTHS_FOR_SEASONALITY = 24
#: A month averaging this far above the overall mean is called seasonal.
SEASONAL_LIFT_PCT = 20.0
#: Customers needed before RFM or churn findings are meaningful.
MIN_CUSTOMERS = advanced_engine.MIN_ENTITIES
#: Churn rate at or above this is a critical retention risk.
CRITICAL_CHURN_PCT = 40.0
HIGH_CHURN_PCT = 20.0
#: Discount rows above this multiple of the average are unusually deep.
DEEP_DISCOUNT_MULTIPLE = 2.0
#: Share of rows outside the expected range before anomalies are notable.
NOTABLE_OUTLIER_PCT = 1.0
#: Distinct values kept per filter list.
MAX_FILTER_VALUES = 50


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _fmt(value: float | None, suffix: str = "") -> str:
    """Display form for a figure. Matches the report renderers' grouping."""
    number = _round(value)
    if number is None:
        return "n/a"
    if number == int(number) and abs(number) < 1e15:
        return f"{int(number):,}{suffix}"
    return f"{number:,.2f}{suffix}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def evidence(
    label: str, value: float | None, *, detail: str | None = None, suffix: str = ""
) -> Evidence:
    return Evidence(
        label=label, value=_round(value), formatted=_fmt(value, suffix), detail=detail
    )


def text_evidence(label: str, text: str, *, detail: str | None = None) -> Evidence:
    """Evidence whose value is a label rather than a number (a region, a month)."""
    return Evidence(label=label, value=None, formatted=text, detail=detail)


# --- Prioritisation ----------------------------------------------------------

#: Points contributed by severity. The dominant term, but not the only one.
_SEVERITY_POINTS = {
    Severity.CRITICAL: 50.0,
    Severity.HIGH: 38.0,
    Severity.MEDIUM: 22.0,
    Severity.LOW: 10.0,
    Severity.INFO: 4.0,
}


def priority_for(
    severity: InsightSeverity,
    *,
    magnitude_pct: float | None = None,
    coverage: float | None = None,
    persistence_periods: int | None = None,
    confidence: float | None = None,
) -> tuple[InsightPriority, float, str]:
    """Rank a finding from its measured properties.

    Deliberately a transparent formula rather than a model: the caller stores
    the score and the sentence explaining it, so the ordering on the page can
    always be justified. Every term is optional - a finding contributes only
    what was actually measured.
    """
    score = _SEVERITY_POINTS[severity]
    parts = [f"severity {severity.value} (+{_SEVERITY_POINTS[severity]:.0f})"]

    if magnitude_pct is not None:
        # Capped so one runaway percentage cannot dominate the ranking.
        points = min(abs(magnitude_pct) / 2.0, 25.0)
        score += points
        parts.append(f"magnitude {abs(magnitude_pct):.1f}% (+{points:.0f})")

    if coverage is not None:
        points = min(max(coverage, 0.0), 1.0) * 15.0
        score += points
        parts.append(f"covers {coverage * 100:.0f}% of the data (+{points:.0f})")

    if persistence_periods is not None and persistence_periods >= MIN_PERIODS_FOR_TREND:
        points = min((persistence_periods - MIN_PERIODS_FOR_TREND + 1) * 2.0, 10.0)
        score += points
        parts.append(f"sustained over {persistence_periods} periods (+{points:.0f})")

    if confidence is not None:
        points = min(max(confidence, 0.0), 1.0) * 10.0
        score += points
        parts.append(f"confidence {confidence:.2f} (+{points:.0f})")

    if score >= 70:
        priority = Priority.CRITICAL
    elif score >= 50:
        priority = Priority.HIGH
    elif score >= 28:
        priority = Priority.MEDIUM
    else:
        priority = Priority.LOW

    return priority, round(score, 1), "; ".join(parts)


def _insight(
    identifier: str,
    category: InsightCategory,
    title: str,
    summary: str,
    severity: InsightSeverity,
    source: str,
    *,
    why: str | None = None,
    action: str | None = None,
    recommendation: str | None = None,
    metric: str | None = None,
    metric_value: float | None = None,
    comparison_value: float | None = None,
    percentage_change: float | None = None,
    dimension: str | None = None,
    dimension_value: str | None = None,
    items: Sequence[Evidence] = (),
    confidence: float | None = None,
    affected_records: int | None = None,
    coverage: float | None = None,
    persistence_periods: int | None = None,
) -> BusinessInsight:
    priority, score, reason = priority_for(
        severity,
        magnitude_pct=percentage_change,
        coverage=coverage,
        persistence_periods=persistence_periods,
        confidence=confidence,
    )
    return BusinessInsight(
        id=identifier,
        category=category,
        title=title,
        summary=summary,
        severity=severity,
        priority=priority,
        metric=metric,
        metric_value=_round(metric_value),
        comparison_value=_round(comparison_value),
        percentage_change=_round(percentage_change),
        dimension=dimension,
        dimension_value=dimension_value,
        why=why,
        action=action,
        evidence=list(items),
        confidence=confidence,
        affected_records=affected_records,
        recommendation=recommendation or action,
        source=source,
        priority_score=score,
        priority_reason=reason,
        created_at=datetime.now(UTC),
    )


# --- A. Performance and B. trend changes -------------------------------------


def _trend_severity(change: float | None, growing: bool) -> InsightSeverity:
    if change is None:
        return Severity.INFO
    if not growing and change <= SHARP_DECLINE_PCT:
        return Severity.HIGH
    if not growing:
        return Severity.MEDIUM
    return Severity.LOW if change < STRONG_GROWTH_PCT else Severity.INFO


def detect_performance(analyst: AnalystReport, model: SemanticModel) -> list[BusinessInsight]:
    """Movement in each trended measure, read off the analyst's own trends.

    Only measures where "up is good" are read here. Rating and delivery have
    their own polarity and belong to the operational detector - a falling
    delivery time is an improvement, and reporting it as a decline would be
    wrong rather than merely noisy.
    """
    found: list[BusinessInsight] = []
    owned_elsewhere = {
        column
        for column in (model.get("rating"), model.get("delivery"), model.get("discount"))
        if column
    }

    for index, trend in enumerate(analyst.trends):
        if trend.direction is TrendDirection.INSUFFICIENT_DATA:
            continue
        if trend.metric_column in owned_elsewhere:
            continue
        change = trend.percentage_change
        if change is None or abs(change) < MATERIAL_CHANGE_PCT:
            continue

        growing = change > 0
        column = trend.metric_column
        items = [
            evidence(f"{column} ({trend.last_label})", trend.last_value),
            evidence(f"{column} ({trend.first_label})", trend.first_value),
            evidence("Change", change, suffix="%"),
            text_evidence("Granularity", f"by {trend.period.value}"),
            evidence("Periods observed", float(trend.periods_observed)),
            text_evidence(
                "Peak", f"{trend.highest_label} ({_fmt(trend.highest_value)})"
            ),
            text_evidence("Low", f"{trend.lowest_label} ({_fmt(trend.lowest_value)})"),
        ]

        if growing:
            found.append(
                _insight(
                    f"performance-{column}-up",
                    Category.PERFORMANCE,
                    f"{column} is up {change:.1f}%",
                    (
                        f"{column} moved {_pct(change)} from {trend.first_label} "
                        f"({_fmt(trend.first_value)}) to {trend.last_label} "
                        f"({_fmt(trend.last_value)}), measured by {trend.period.value}."
                    ),
                    _trend_severity(change, growing=True),
                    source="trend analysis",
                    why=(
                        "Sustained growth in a headline measure is the clearest signal "
                        "of where the business is currently working."
                    ),
                    action=(
                        f"Identify what changed between {trend.first_label} and "
                        f"{trend.last_label} and whether it can be repeated."
                    ),
                    metric=column,
                    metric_value=trend.last_value,
                    comparison_value=trend.first_value,
                    percentage_change=change,
                    dimension=column,
                    items=items,
                    persistence_periods=trend.periods_observed,
                )
            )
        else:
            found.append(
                _insight(
                    f"performance-{column}-down",
                    Category.RISK,
                    f"{column} is down {abs(change):.1f}%",
                    (
                        f"Potential risk detected: {column} fell {_pct(change)} from "
                        f"{trend.first_label} ({_fmt(trend.first_value)}) to "
                        f"{trend.last_label} ({_fmt(trend.last_value)}). The cause is "
                        "not established by this data alone."
                    ),
                    _trend_severity(change, growing=False),
                    source="trend analysis",
                    why=(
                        "A falling headline measure compounds if it is not addressed, "
                        "and the decline is visible across several periods."
                    ),
                    action=(
                        f"Investigate what changed around {trend.last_label} before the "
                        "trend continues."
                    ),
                    metric=column,
                    metric_value=trend.last_value,
                    comparison_value=trend.first_value,
                    percentage_change=change,
                    dimension=column,
                    items=items,
                    persistence_periods=trend.periods_observed,
                )
            )

        # A sudden single-period move is a different finding from the overall
        # direction, and is often the more actionable of the two.
        found.extend(_sudden_change(trend, index))

    return found


def _sudden_change(trend: TrendFinding, index: int) -> list[BusinessInsight]:
    """Flag a peak or trough that sits far from the rest of the series."""
    if trend.periods_observed < MIN_PERIODS_FOR_TREND:
        return []
    if trend.highest_value is None or trend.lowest_value is None:
        return []
    if trend.last_value is None or trend.last_value == 0:
        return []

    # Only worth reporting when the extreme is the most recent period, which is
    # what makes it actionable rather than historical.
    if trend.lowest_label == trend.last_label and trend.highest_value:
        drop = ((trend.lowest_value - trend.highest_value) / trend.highest_value) * 100
        if drop <= SHARP_DECLINE_PCT:
            return [
                _insight(
                    f"sudden-drop-{trend.metric_column}-{index}",
                    Category.RISK,
                    f"{trend.metric_column} is at its lowest in {trend.last_label}",
                    (
                        f"Potential risk detected: the most recent period "
                        f"({trend.last_label}) is the lowest {trend.metric_column} in "
                        f"the observed history, {_pct(drop)} below the peak at "
                        f"{trend.highest_label}."
                    ),
                    Severity.HIGH,
                    source="trend analysis",
                    why="The latest period being the worst on record suggests an ongoing issue.",
                    action=(
                        f"Compare {trend.last_label} against {trend.highest_label} to "
                        "isolate what changed."
                    ),
                    metric=trend.metric_column,
                    metric_value=trend.lowest_value,
                    comparison_value=trend.highest_value,
                    percentage_change=drop,
                    dimension=trend.metric_column,
                    items=[
                        text_evidence("Latest period", str(trend.last_label)),
                        evidence("Latest value", trend.lowest_value),
                        text_evidence("Peak period", str(trend.highest_label)),
                        evidence("Peak value", trend.highest_value),
                    ],
                    persistence_periods=trend.periods_observed,
                )
            ]
    return []


def detect_seasonality(
    frame: pd.DataFrame, model: SemanticModel
) -> tuple[list[BusinessInsight], list[dict[str, str]]]:
    """Repeated calendar-month strength, only with enough history to see it."""
    date_column = model.get("date")
    revenue = model.get("revenue")
    if not date_column or not revenue:
        return [], []

    try:
        dates = analytics_engine.parse_dates(frame, date_column)
    except AppError as exc:
        return [], [{"analysis": "seasonality", "reason": exc.message}]

    values = pd.to_numeric(frame[revenue], errors="coerce")
    paired = pd.DataFrame({"date": dates, "value": values}).dropna()
    if paired.empty:
        return [], []

    months_covered = paired["date"].dt.to_period("M").nunique()
    if months_covered < MIN_MONTHS_FOR_SEASONALITY:
        return [], [
            {
                "analysis": "seasonality",
                "reason": (
                    f"Seasonal patterns need at least {MIN_MONTHS_FOR_SEASONALITY} "
                    f"months of history to separate from noise; this dataset covers "
                    f"{months_covered}."
                ),
            }
        ]

    # Mean per calendar month across years, so a single strong year cannot
    # masquerade as a repeating season.
    monthly = paired.groupby(paired["date"].dt.month)["value"].mean()
    overall = float(monthly.mean())
    if overall == 0:
        return [], []

    best_month = int(monthly.idxmax())
    lift = ((float(monthly.max()) - overall) / overall) * 100
    if lift < SEASONAL_LIFT_PCT:
        return [], []

    name = datetime(2000, best_month, 1).strftime("%B")
    return [
        _insight(
            "seasonality-revenue",
            Category.TREND,
            f"{revenue} peaks in {name}",
            (
                f"Across {months_covered} months of history, {name} averages "
                f"{_fmt(float(monthly.max()))} in {revenue} - {lift:.1f}% above the "
                f"all-month average of {_fmt(overall)}. This is a repeated pattern in "
                "the data, not a forecast."
            ),
            Severity.LOW,
            source="seasonal analysis",
            why="A repeating seasonal peak lets stock, staffing and spend be planned ahead.",
            action=f"Plan capacity and campaigns around the {name} peak.",
            metric=revenue,
            metric_value=float(monthly.max()),
            comparison_value=overall,
            percentage_change=lift,
            dimension=date_column,
            dimension_value=name,
            items=[
                text_evidence("Strongest month", name),
                evidence(f"Average {revenue} in {name}", float(monthly.max())),
                evidence("Average across all months", overall),
                evidence("Lift", lift, suffix="%"),
                evidence("Months of history", float(months_covered)),
            ],
        )
    ], []


# --- C/D. Dimension performance (category, region, channel) ------------------


def _dimension_change(
    frame: pd.DataFrame,
    dimension: str,
    date_column: str,
    metric_column: str,
    period: TimePeriod,
) -> list[tuple[str, float | None, float | None, float | None]]:
    """Latest vs previous period per group, using the existing time series.

    Returns (group, latest, previous, percentage change).
    """
    try:
        series = analytics_engine.build_time_series(
            frame,
            TimeSeriesRequest(
                date_column=date_column,
                period=period,
                metric=MetricType.SUM,
                column=metric_column,
                group_by=dimension,
                max_points=500,
            ),
        )
    except AppError as exc:
        logger.info("Dimension trend skipped for %s: %s", dimension, exc.message)
        return []

    rows: list[tuple[str, float | None, float | None, float | None]] = []
    for group in series.series:
        points = [point for point in group.points if point.value is not None]
        if len(points) < MIN_PERIODS_FOR_COMPARISON:
            continue
        latest, previous = points[-1].value, points[-2].value
        change = (
            None
            if latest is None or not previous
            else ((latest - previous) / previous) * 100
        )
        rows.append((group.name, latest, previous, _round(change)))
    return rows


def _dimension_insights(
    frame: pd.DataFrame,
    model: SemanticModel,
    analyst: AnalystReport,
    role: str,
    category: InsightCategory,
    noun: str,
) -> list[BusinessInsight]:
    """Leaders, laggards, concentration and movement for one dimension."""
    dimension = model.get(role)
    revenue = model.get("revenue")
    if not dimension or not revenue:
        return []

    found: list[BusinessInsight] = []

    # Ranking comes from the analyst's segment findings - already computed.
    segment = next(
        (item for item in analyst.segments if item.dimension == dimension), None
    )
    if segment and segment.top:
        best = segment.top[0]
        share = best.get("percentage")
        group_count = len(segment.top)

        found.append(
            _insight(
                f"{role}-leader",
                Category.OPPORTUNITY,
                f"'{best['label']}' is the strongest {noun}",
                (
                    f"'{best['label']}' leads {dimension} with {_fmt(best.get('value'))} "
                    f"in {revenue}"
                    + (f", {share:.1f}% of the total" if share is not None else "")
                    + "."
                ),
                Severity.INFO,
                source=f"{noun} performance",
                why=(
                    f"The strongest {noun} is where additional investment has already "
                    "been shown to convert in this data."
                ),
                action=(
                    f"Consider whether '{best['label']}' has room to expand, and what "
                    "makes it outperform the rest."
                ),
                metric=revenue,
                metric_value=best.get("value"),
                dimension=dimension,
                dimension_value=str(best["label"]),
                items=[
                    text_evidence(f"Top {noun}", str(best["label"])),
                    evidence(f"{revenue}", best.get("value")),
                    evidence("Share of total", share, suffix="%"),
                ]
                + [
                    text_evidence(
                        f"#{position}", f"{row['label']} ({_fmt(row.get('value'))})"
                    )
                    for position, row in enumerate(segment.top[1:4], start=2)
                ],
                confidence=(share / 100) if share is not None else None,
            )
        )

        if share is not None and share >= CONCENTRATION_PCT and group_count >= MIN_GROUPS:
            found.append(
                _insight(
                    f"{role}-concentration",
                    Category.RISK,
                    f"{revenue} is concentrated in one {noun}",
                    (
                        f"Potential risk detected: '{best['label']}' alone accounts for "
                        f"{share:.1f}% of {revenue}. Losing it would remove a large "
                        "share of the total."
                    ),
                    Severity.HIGH if share >= 70 else Severity.MEDIUM,
                    source=f"{noun} concentration",
                    why=(
                        "Dependence on a single group makes total performance fragile "
                        "to one customer, supplier or market moving away."
                    ),
                    action=f"Grow the next-largest {noun}s to reduce the dependence.",
                    metric="concentration",
                    metric_value=share,
                    dimension=dimension,
                    dimension_value=str(best["label"]),
                    items=[
                        text_evidence(f"Leading {noun}", str(best["label"])),
                        evidence("Share of total", share, suffix="%"),
                        evidence(
                            "Groups making up 80% of the total",
                            float(segment.class_a_count)
                            if segment.class_a_count is not None
                            else None,
                        ),
                    ],
                    confidence=share / 100,
                )
            )

    # Movement per group needs a time axis; without one, ranking is all we have.
    date_column = model.get("date")
    if not date_column:
        return found

    period = insight_engine._choose_period(frame, date_column)
    changes = [
        row for row in _dimension_change(frame, dimension, date_column, revenue, period)
        if row[3] is not None
    ]
    if not changes:
        return found

    changes.sort(key=lambda row: row[3] or 0.0)
    worst, best_mover = changes[0], changes[-1]

    if worst[3] is not None and worst[3] <= -MATERIAL_CHANGE_PCT:
        found.append(
            _insight(
                f"{role}-declining",
                category,
                f"'{worst[0]}' {noun} is declining",
                (
                    f"Potential risk detected: {revenue} for '{worst[0]}' fell "
                    f"{_pct(worst[3])} in the latest {period.value}, from "
                    f"{_fmt(worst[2])} to {_fmt(worst[1])}. This compares two periods "
                    "and does not by itself establish a cause."
                ),
                Severity.HIGH if worst[3] <= SHARP_DECLINE_PCT else Severity.MEDIUM,
                source=f"{noun} trend",
                why=(
                    f"A {noun} moving against the rest of the business usually has a "
                    "specific, addressable reason."
                ),
                action=f"Review pricing, availability and demand for '{worst[0]}'.",
                metric=revenue,
                metric_value=worst[1],
                comparison_value=worst[2],
                percentage_change=worst[3],
                dimension=dimension,
                dimension_value=str(worst[0]),
                items=[
                    text_evidence(noun.capitalize(), str(worst[0])),
                    evidence(f"Latest {period.value}", worst[1]),
                    evidence(f"Previous {period.value}", worst[2]),
                    evidence("Change", worst[3], suffix="%"),
                ],
            )
        )

    if best_mover[3] is not None and best_mover[3] >= STRONG_GROWTH_PCT:
        found.append(
            _insight(
                f"{role}-growing",
                Category.OPPORTUNITY,
                f"'{best_mover[0]}' {noun} is growing fast",
                (
                    f"{revenue} for '{best_mover[0]}' rose {_pct(best_mover[3])} in the "
                    f"latest {period.value}, from {_fmt(best_mover[2])} to "
                    f"{_fmt(best_mover[1])}."
                ),
                Severity.LOW,
                source=f"{noun} trend",
                why=f"A fast-growing {noun} is the cheapest place to add more capacity.",
                action=f"Check whether '{best_mover[0]}' can absorb more stock or spend.",
                metric=revenue,
                metric_value=best_mover[1],
                comparison_value=best_mover[2],
                percentage_change=best_mover[3],
                dimension=dimension,
                dimension_value=str(best_mover[0]),
                items=[
                    text_evidence(noun.capitalize(), str(best_mover[0])),
                    evidence(f"Latest {period.value}", best_mover[1]),
                    evidence(f"Previous {period.value}", best_mover[2]),
                    evidence("Change", best_mover[3], suffix="%"),
                ],
            )
        )

    return found


# --- E. Customer insights ----------------------------------------------------


@dataclass
class CustomerAnalytics:
    """RFM and churn, computed once and shared.

    Both the customer detectors and the business-health score need these, and
    they are the most expensive analyses in the pipeline - so they are run in
    one place and passed around rather than recomputed per consumer.
    """

    customer_column: str | None = None
    date_column: str | None = None
    revenue_column: str | None = None
    rfm_segments: list[RfmSegmentSummary] = field(default_factory=list)
    rfm_context: dict[str, Any] = field(default_factory=dict)
    churn: dict[str, Any] | None = None
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.customer_column is not None and self.date_column is not None


def build_customer_analytics(frame: pd.DataFrame, model: SemanticModel) -> CustomerAnalytics:
    """Run RFM and churn once, reporting rather than raising on failure."""
    customer = model.get("customer") or (
        model.identifiers[0].name if model.identifiers else None
    )
    date_column = model.get("date")
    revenue = model.get("revenue")

    analytics = CustomerAnalytics(
        customer_column=customer, date_column=date_column, revenue_column=revenue
    )

    if not customer or not date_column:
        analytics.skipped.append(
            {
                "analysis": "customer insights",
                "reason": (
                    "Customer analysis needs a customer/entity identifier and a "
                    "transaction date. This dataset does not have both."
                ),
            }
        )
        return analytics

    if revenue:
        try:
            segments, _customers, context = advanced_engine.build_rfm(
                frame, customer, date_column, revenue
            )
        except AppError as exc:
            analytics.skipped.append({"analysis": "RFM", "reason": exc.message})
        else:
            analytics.rfm_segments = segments
            analytics.rfm_context = context

    try:
        analytics.churn = advanced_engine.build_churn(
            frame, customer, date_column, revenue, 90, 45, 10
        )
    except AppError as exc:
        analytics.skipped.append({"analysis": "churn", "reason": exc.message})

    return analytics


def detect_customers(
    analytics: CustomerAnalytics,
) -> tuple[list[BusinessInsight], list[dict[str, str]], list[str]]:
    """RFM and churn findings. Returns (insights, skipped, segment names)."""
    if not analytics.available:
        return [], [], []

    customer = str(analytics.customer_column)
    revenue = analytics.revenue_column

    found: list[BusinessInsight] = []
    skipped: list[dict[str, str]] = []
    segment_names: list[str] = []

    if revenue and analytics.rfm_segments:
        segments, context = analytics.rfm_segments, analytics.rfm_context
        segment_names = [item.segment.value for item in segments]
        total_customers = int(context["customer_count"])

        champions = next(
            (item for item in segments if item.segment.value == "champions"), None
        )
        if champions and champions.customer_count:
            found.append(
                _insight(
                    "customer-champions",
                    Category.CUSTOMER,
                    f"{champions.customer_count:,} champion customers drive "
                    f"{champions.monetary_percentage:.1f}% of value",
                    (
                        f"{champions.customer_count:,} customers "
                        f"({champions.percentage:.1f}% of the base) contribute "
                        f"{_fmt(champions.total_monetary)} - "
                        f"{champions.monetary_percentage:.1f}% of total {revenue}."
                    ),
                    Severity.INFO,
                    source="RFM analysis",
                    why=(
                        "A small, identifiable group carrying a large share of value "
                        "is the highest-return group to retain."
                    ),
                    action=(
                        "Give this segment priority in retention, service and early "
                        "access to new products."
                    ),
                    metric=revenue,
                    metric_value=champions.total_monetary,
                    dimension=customer,
                    dimension_value="champions",
                    items=[
                        evidence("Champion customers", float(champions.customer_count)),
                        evidence("Share of customers", champions.percentage, suffix="%"),
                        evidence(f"Total {revenue}", champions.total_monetary),
                        evidence(
                            "Share of value", champions.monetary_percentage, suffix="%"
                        ),
                        evidence(
                            "Average purchases each", champions.average_frequency
                        ),
                    ],
                    affected_records=champions.customer_count,
                    confidence=champions.monetary_percentage / 100,
                )
            )

        at_risk = [
            item
            for item in segments
            if item.segment.value in ("at_risk", "cannot_lose_them", "hibernating")
        ]
        at_risk_count = sum(item.customer_count for item in at_risk)
        at_risk_value = sum(item.total_monetary for item in at_risk)
        if at_risk_count and total_customers:
            share = (at_risk_count / total_customers) * 100
            value_share = sum(item.monetary_percentage for item in at_risk)
            found.append(
                _insight(
                    "customer-at-risk-rfm",
                    Category.RISK,
                    f"{at_risk_count:,} previously valuable customers have gone quiet",
                    (
                        f"Potential risk detected: {at_risk_count:,} customers "
                        f"({share:.1f}% of the base) fall into at-risk, "
                        f"cannot-lose-them or hibernating segments, together "
                        f"representing {_fmt(at_risk_value)} "
                        f"({value_share:.1f}%) of historical {revenue}."
                    ),
                    Severity.HIGH if value_share >= 25 else Severity.MEDIUM,
                    source="RFM analysis",
                    why=(
                        "These customers have already bought, so re-engaging them is "
                        "usually cheaper than acquiring new ones."
                    ),
                    action=(
                        "Run a targeted win-back contact for this segment and measure "
                        "the response before scaling it."
                    ),
                    metric=revenue,
                    metric_value=at_risk_value,
                    dimension=customer,
                    dimension_value="at risk",
                    items=[
                        evidence("Customers affected", float(at_risk_count)),
                        evidence("Share of customer base", share, suffix="%"),
                        evidence("Historical value", at_risk_value),
                        evidence("Share of value", value_share, suffix="%"),
                    ]
                    + [
                        text_evidence(
                            item.segment.value.replace("_", " ").title(),
                            f"{item.customer_count:,} customers, "
                            f"{_fmt(item.total_monetary)}",
                        )
                        for item in at_risk
                    ],
                    affected_records=at_risk_count,
                    coverage=at_risk_count / total_customers,
                    confidence=value_share / 100,
                )
            )

    churn = analytics.churn
    if churn is None:
        return found, skipped, segment_names

    total = int(churn["total_customers"])
    if total >= MIN_CUSTOMERS:
        rate = float(churn["churn_rate"])
        severity = (
            Severity.CRITICAL
            if rate >= CRITICAL_CHURN_PCT
            else Severity.HIGH
            if rate >= HIGH_CHURN_PCT
            else Severity.LOW
        )
        items = [
            evidence("Total customers", float(total)),
            evidence("Active", float(churn["active_customers"])),
            evidence("At risk (45+ days quiet)", float(churn["at_risk_customers"])),
            evidence("Churned (90+ days quiet)", float(churn["churned_customers"])),
            evidence("Churn rate", rate, suffix="%"),
            text_evidence("Measured against", str(churn["reference_date"])),
        ]
        if churn.get("revenue_at_risk") is not None:
            items.append(evidence("Value at risk", float(churn["revenue_at_risk"])))

        if rate >= HIGH_CHURN_PCT:
            found.append(
                _insight(
                    "customer-churn",
                    Category.RISK,
                    f"{rate:.1f}% of customers have gone inactive",
                    (
                        f"Potential risk detected: {churn['churned_customers']:,} of "
                        f"{total:,} customers have had no recorded activity for 90+ days, "
                        f"a churn rate of {rate:.1f}%. A further "
                        f"{churn['at_risk_customers']:,} are quiet for 45+ days. This is "
                        "an inactivity rule applied to recorded activity, not a "
                        "predictive model."
                    ),
                    severity,
                    source="churn analysis",
                    why=(
                        "Inactive customers stop contributing revenue while acquisition "
                        "costs to replace them continue."
                    ),
                    action=(
                        "Confirm whether these customers are genuinely lost or simply "
                        "absent from this dataset, then prioritise the at-risk group."
                    ),
                    metric="churn_rate",
                    metric_value=rate,
                    dimension=customer,
                    items=items,
                    affected_records=int(churn["churned_customers"]),
                    coverage=float(churn["churned_customers"]) / total,
                )
            )
        else:
            found.append(
                _insight(
                    "customer-retention-strong",
                    Category.CUSTOMER,
                    f"Retention is holding at {100 - rate:.1f}%",
                    (
                        f"{churn['active_customers']:,} of {total:,} customers have "
                        f"recorded activity within the last 90 days, leaving a churn "
                        f"rate of {rate:.1f}%."
                    ),
                    Severity.INFO,
                    source="churn analysis",
                    why="Stable retention means growth compounds rather than replacing losses.",
                    action="Keep the current retention approach and watch the at-risk group.",
                    metric="churn_rate",
                    metric_value=rate,
                    dimension=customer,
                    items=items,
                )
            )
    else:
        skipped.append(
            {
                "analysis": "churn",
                "reason": (
                    f"Only {total} distinct customers were found; at least "
                    f"{MIN_CUSTOMERS} are needed for retention figures to be meaningful."
                ),
            }
        )

    return found, skipped, segment_names


# --- F. Discount and pricing -------------------------------------------------


def detect_pricing(
    frame: pd.DataFrame, model: SemanticModel, analyst: AnalystReport
) -> list[BusinessInsight]:
    """Discount depth, concentration, and its association with revenue."""
    discount = model.get("discount")
    revenue = model.get("revenue")
    if not discount:
        return []

    values = pd.to_numeric(frame[discount], errors="coerce").dropna()
    if values.empty or values.nunique() <= 1:
        return []

    found: list[BusinessInsight] = []
    average = float(values.mean())
    threshold = average * DEEP_DISCOUNT_MULTIPLE
    deep = values[values >= threshold]
    row_count = len(frame)

    if len(deep) and average > 0:
        share = (len(deep) / row_count) * 100
        found.append(
            _insight(
                "pricing-deep-discounts",
                Category.OPPORTUNITY if share < 5 else Category.RISK,
                f"{len(deep):,} rows carry unusually deep {discount}",
                (
                    f"{len(deep):,} rows ({share:.1f}%) have a {discount} of at least "
                    f"{_fmt(threshold)}, which is {DEEP_DISCOUNT_MULTIPLE:.0f}x the "
                    f"average of {_fmt(average)}. The deepest observed is "
                    f"{_fmt(float(values.max()))}."
                ),
                Severity.MEDIUM if share >= 5 else Severity.LOW,
                source="discount analysis",
                why=(
                    "Discounting far above the norm erodes margin, and is worth "
                    "confirming as deliberate rather than accidental."
                ),
                action=(
                    f"Review whether the deepest {discount} values are approved policy "
                    "or data-entry errors."
                ),
                metric=discount,
                metric_value=float(deep.mean()),
                comparison_value=average,
                dimension=discount,
                items=[
                    evidence(f"Average {discount}", average),
                    evidence("Deep-discount threshold", threshold),
                    evidence("Rows above threshold", float(len(deep))),
                    evidence("Share of rows", share, suffix="%"),
                    evidence(f"Highest {discount}", float(values.max())),
                ],
                affected_records=int(len(deep)),
                coverage=len(deep) / row_count,
            )
        )

    # Where the discounting concentrates, when there is a dimension to group by.
    dimension = model.get("product") or model.get("region")
    if dimension:
        try:
            grouped = analytics_engine.build_segment(
                frame,
                SegmentRequest(
                    dimension=dimension,
                    metric=MetricType.AVERAGE,
                    column=discount,
                    limit=5,
                ),
            )
        except AppError:
            grouped = None
        if grouped and grouped.rows and grouped.group_count >= MIN_GROUPS:
            worst = grouped.rows[0]
            if worst.value is not None and average > 0:
                lift = ((worst.value - average) / average) * 100
                if lift >= STRONG_GROWTH_PCT:
                    found.append(
                        _insight(
                            "pricing-concentration",
                            Category.RISK,
                            f"Discounting is concentrated in '{worst.label}'",
                            (
                                f"Potential risk detected: '{worst.label}' averages "
                                f"{_fmt(worst.value)} in {discount}, {lift:.1f}% above "
                                f"the dataset average of {_fmt(average)}."
                            ),
                            Severity.MEDIUM,
                            source="discount analysis",
                            why=(
                                "Uneven discounting can quietly move margin between "
                                "groups without a deliberate decision."
                            ),
                            action=(
                                f"Check whether the {discount} level for '{worst.label}' "
                                "is intentional."
                            ),
                            metric=discount,
                            metric_value=worst.value,
                            comparison_value=average,
                            percentage_change=lift,
                            dimension=dimension,
                            dimension_value=str(worst.label),
                            items=[
                                text_evidence("Group", str(worst.label)),
                                evidence(f"Average {discount} here", worst.value),
                                evidence("Dataset average", average),
                                evidence("Difference", lift, suffix="%"),
                            ]
                            + [
                                text_evidence(str(row.label), _fmt(row.value))
                                for row in grouped.rows[1:4]
                            ],
                        )
                    )

    # The discount/revenue association is already computed by the analyst.
    if revenue:
        relationship = next(
            (
                item
                for item in analyst.insights
                if item.metric == "correlation" and item.dimension == discount
            ),
            None,
        )
        if relationship and relationship.value is not None:
            strength = abs(relationship.value)
            found.append(
                _insight(
                    "pricing-revenue-association",
                    Category.PERFORMANCE,
                    f"{discount} moves with {revenue}",
                    (
                        f"{relationship.summary} Acting on this should be tested rather "
                        "than assumed."
                    ),
                    Severity.LOW if strength < 0.5 else Severity.MEDIUM,
                    source="correlation analysis",
                    why=(
                        "If discounting genuinely moves revenue, discount policy becomes "
                        "a lever; if not, it is only cost."
                    ),
                    action=(
                        f"Run a controlled test changing {discount} on a subset before "
                        "changing policy broadly."
                    ),
                    metric="correlation",
                    metric_value=relationship.value,
                    dimension=discount,
                    items=[
                        evidence("Correlation coefficient", relationship.value),
                        text_evidence("Compared against", revenue),
                        evidence(
                            "Rows compared",
                            float(relationship.supporting_data.get("rows", 0)) or None,
                        ),
                    ],
                    confidence=strength,
                )
            )

    return found


# --- G. Operations -----------------------------------------------------------


def detect_operations(
    frame: pd.DataFrame, model: SemanticModel, analyst: AnalystReport
) -> list[BusinessInsight]:
    """Delivery performance and rating movement, where those columns exist."""
    found: list[BusinessInsight] = []

    delivery = model.get("delivery")
    if delivery:
        values = pd.to_numeric(frame[delivery], errors="coerce").dropna()
        if not values.empty and values.nunique() > 1:
            average = float(values.mean())
            slow_threshold = float(values.quantile(0.9))
            slow = values[values >= slow_threshold]
            dimension = model.get("region") or model.get("product")

            items = [
                evidence(f"Average {delivery}", average),
                evidence("Median", float(values.median())),
                evidence("Slowest 10% start at", slow_threshold),
                evidence("Worst observed", float(values.max())),
                evidence("Rows in the slowest 10%", float(len(slow))),
            ]
            if dimension:
                try:
                    grouped = analytics_engine.build_segment(
                        frame,
                        SegmentRequest(
                            dimension=dimension,
                            metric=MetricType.AVERAGE,
                            column=delivery,
                            limit=3,
                        ),
                    )
                    items.extend(
                        text_evidence(f"Slowest {dimension}: {row.label}", _fmt(row.value))
                        for row in grouped.rows[:3]
                    )
                except AppError:
                    pass

            found.append(
                _insight(
                    "operations-delivery",
                    Category.OPERATIONS,
                    f"Slowest 10% of {delivery} is {slow_threshold:,.1f} or worse",
                    (
                        f"{delivery} averages {_fmt(average)}, but the slowest 10% of "
                        f"records sit at {_fmt(slow_threshold)} or above, reaching "
                        f"{_fmt(float(values.max()))} at worst."
                    ),
                    Severity.MEDIUM if slow_threshold >= average * 2 else Severity.LOW,
                    source="operational analysis",
                    why=(
                        "The long tail of slow fulfilment, not the average, is what "
                        "customers complain about."
                    ),
                    action=f"Investigate the records in the slowest {delivery} decile.",
                    metric=delivery,
                    metric_value=slow_threshold,
                    comparison_value=average,
                    dimension=delivery,
                    items=items,
                    affected_records=int(len(slow)),
                )
            )

    delivery_trend = next(
        (item for item in analyst.trends if item.metric_column == delivery), None
    )
    if (
        delivery_trend
        and delivery_trend.direction is not TrendDirection.INSUFFICIENT_DATA
        and delivery_trend.percentage_change is not None
        and abs(delivery_trend.percentage_change) >= MATERIAL_CHANGE_PCT
    ):
        # Rising delivery time is a deterioration; falling time is an improvement.
        worsening = delivery_trend.percentage_change > 0
        change = delivery_trend.percentage_change
        found.append(
            _insight(
                "operations-delivery-trend",
                Category.OPERATIONS,
                f"{delivery} is {'rising' if worsening else 'improving'}",
                (
                    (
                        f"Potential risk detected: {delivery} rose {_pct(change)} from "
                        if worsening
                        else f"{delivery} fell {_pct(change)} from "
                    )
                    + f"{delivery_trend.first_label} ({_fmt(delivery_trend.first_value)}) "
                    f"to {delivery_trend.last_label} ({_fmt(delivery_trend.last_value)}). "
                    + (
                        "Longer fulfilment times usually show up in satisfaction next."
                        if worsening
                        else "Shorter fulfilment times are an improvement."
                    )
                ),
                (Severity.HIGH if change >= abs(SHARP_DECLINE_PCT) else Severity.MEDIUM)
                if worsening
                else Severity.INFO,
                source="trend analysis",
                why=(
                    "Fulfilment time is one of the few operational measures a customer "
                    "experiences directly."
                ),
                action=(
                    f"Find what lengthened {delivery} around {delivery_trend.last_label}."
                    if worsening
                    else f"Identify what shortened {delivery} and keep it in place."
                ),
                metric=delivery,
                metric_value=delivery_trend.last_value,
                comparison_value=delivery_trend.first_value,
                percentage_change=change,
                dimension=delivery,
                items=[
                    evidence(f"Latest {delivery}", delivery_trend.last_value),
                    evidence(f"Earliest {delivery}", delivery_trend.first_value),
                    evidence("Change", change, suffix="%"),
                    evidence("Periods observed", float(delivery_trend.periods_observed)),
                ],
                persistence_periods=delivery_trend.periods_observed,
            )
        )

    rating = model.get("rating")
    rating_trend = next(
        (item for item in analyst.trends if item.metric_column == rating), None
    )
    if (
        rating
        and rating_trend
        and rating_trend.direction is TrendDirection.DECREASING
        and rating_trend.percentage_change is not None
    ):
        found.append(
            _insight(
                "operations-rating-decline",
                Category.OPERATIONS,
                f"{rating} is declining",
                (
                    f"Potential risk detected: average {rating} fell "
                    f"{_pct(rating_trend.percentage_change)} from "
                    f"{rating_trend.first_label} ({_fmt(rating_trend.first_value)}) to "
                    f"{rating_trend.last_label} ({_fmt(rating_trend.last_value)})."
                ),
                Severity.HIGH
                if rating_trend.percentage_change <= SHARP_DECLINE_PCT
                else Severity.MEDIUM,
                source="trend analysis",
                why=(
                    "Falling satisfaction usually precedes falling repeat purchase, so "
                    "it is an early warning rather than a lagging one."
                ),
                action=f"Review what changed in the periods where {rating} dropped.",
                metric=rating,
                metric_value=rating_trend.last_value,
                comparison_value=rating_trend.first_value,
                percentage_change=rating_trend.percentage_change,
                dimension=rating,
                items=[
                    evidence(f"Latest {rating}", rating_trend.last_value),
                    evidence(f"Earliest {rating}", rating_trend.first_value),
                    evidence("Change", rating_trend.percentage_change, suffix="%"),
                    evidence("Periods observed", float(rating_trend.periods_observed)),
                ],
                persistence_periods=rating_trend.periods_observed,
            )
        )

    return found


# --- H. Data quality and anomalies -------------------------------------------


def detect_data_quality(
    quality: DataQualitySummary, analyst: AnalystReport, row_count: int
) -> list[BusinessInsight]:
    """Quality issues and outlier levels, both already computed elsewhere."""
    found: list[BusinessInsight] = []

    for index, issue in enumerate(quality.issues):
        if issue.severity.value not in ("critical", "warning"):
            continue
        found.append(
            _insight(
                f"quality-{index}",
                Category.DATA_QUALITY,
                f"Data quality: {issue.issue_type.value.replace('_', ' ')}",
                issue.message,
                Severity.HIGH if issue.severity.value == "critical" else Severity.MEDIUM,
                source="data quality rules",
                why=(
                    "Every figure in this report is computed from these rows, so a "
                    "quality problem limits how far the findings can be trusted."
                ),
                action="Address this in the Cleaning step before acting on the numbers.",
                metric="affected_rows",
                metric_value=float(issue.affected_rows),
                dimension=issue.column,
                items=[
                    text_evidence("Column", issue.column or "(whole dataset)"),
                    evidence("Rows affected", float(issue.affected_rows)),
                    evidence("Share of rows", issue.affected_percentage, suffix="%"),
                    evidence("Overall quality score", float(quality.score), suffix="/100"),
                ],
                affected_records=issue.affected_rows,
                coverage=(issue.affected_rows / row_count) if row_count else None,
            )
        )

    notable = [
        anomaly
        for anomaly in analyst.anomalies
        if anomaly.outlier_percentage >= NOTABLE_OUTLIER_PCT
    ]
    for anomaly in notable:
        found.append(
            _insight(
                f"anomaly-{anomaly.metric_column}",
                Category.DATA_QUALITY,
                f"Unusual values in {anomaly.metric_column}",
                (
                    f"{anomaly.outlier_count:,} values "
                    f"({anomaly.outlier_percentage:.2f}% of rows) in "
                    f"'{anomaly.metric_column}' fall outside "
                    f"{_fmt(anomaly.lower_bound)} to {_fmt(anomaly.upper_bound)}. These "
                    "may be legitimate and warrant review rather than correction."
                ),
                Severity.MEDIUM if anomaly.outlier_percentage >= 5 else Severity.LOW,
                source="outlier detection (IQR)",
                why=(
                    "Extreme values move averages and totals, so they change the "
                    "headline figures whether or not they are errors."
                ),
                action=f"Review the extreme '{anomaly.metric_column}' values before reporting.",
                metric="outliers",
                metric_value=float(anomaly.outlier_count),
                dimension=anomaly.metric_column,
                items=[
                    evidence("Values outside range", float(anomaly.outlier_count)),
                    evidence("Share of rows", anomaly.outlier_percentage, suffix="%"),
                    evidence("Expected range from", anomaly.lower_bound),
                    evidence("Expected range to", anomaly.upper_bound),
                    evidence("Largest observed", anomaly.maximum_outlier),
                ],
                affected_records=anomaly.outlier_count,
                coverage=anomaly.outlier_percentage / 100,
            )
        )

    return found


# --- Assembly ----------------------------------------------------------------


def distinct_values(frame: pd.DataFrame, column: str | None) -> list[str]:
    """Filter options taken from the data itself, never a hard-coded list."""
    if not column or column not in frame.columns:
        return []
    values = frame[column].dropna().astype(str).value_counts()
    return [str(index) for index in values.head(MAX_FILTER_VALUES).index]


def period_labels(frame: pd.DataFrame, model: SemanticModel) -> list[str]:
    date_column = model.get("date")
    if not date_column:
        return []
    try:
        series = analytics_engine.build_time_series(
            frame,
            TimeSeriesRequest(
                date_column=date_column,
                period=insight_engine._choose_period(frame, date_column),
                metric=MetricType.COUNT,
                max_points=500,
            ),
        )
    except AppError:
        return []
    return series.labels[:MAX_FILTER_VALUES]


def supporting_metrics(analyst: AnalystReport) -> list[Evidence]:
    """Headline figures the insights were drawn from, straight off the analyst."""
    return [
        Evidence(
            label=kpi.name,
            value=_round(kpi.value),
            formatted=_fmt(kpi.value),
            detail=kpi.column,
        )
        for kpi in analyst.kpis
        if kpi.available and kpi.value is not None
    ]


def detect_all(
    frame: pd.DataFrame,
    model: SemanticModel,
    analyst: AnalystReport,
    quality: DataQualitySummary,
    customers: CustomerAnalytics,
) -> tuple[list[BusinessInsight], list[dict[str, str]], list[str]]:
    """Run every detector. Returns (insights, skipped analyses, RFM segments).

    ``customers`` is built once by the caller and shared with the health score,
    so RFM and churn are never run twice for the same frame.

    A detector that raises is recorded as skipped rather than failing the run -
    one degenerate column must not cost the user every other finding.
    """
    found: list[BusinessInsight] = []
    skipped: list[dict[str, str]] = list(customers.skipped)
    segments: list[str] = []

    def run(name: str, work: Any) -> None:
        try:
            found.extend(work())
        except Exception:
            logger.exception("Insight detector %s failed", name)
            skipped.append(
                {
                    "analysis": name,
                    "reason": f"{name.capitalize()} could not be computed from this dataset.",
                }
            )

    run("performance", lambda: detect_performance(analyst, model))
    run("pricing", lambda: detect_pricing(frame, model, analyst))
    run("operations", lambda: detect_operations(frame, model, analyst))
    run(
        "data quality",
        lambda: detect_data_quality(quality, analyst, int(len(frame))),
    )
    run(
        "product performance",
        lambda: _dimension_insights(
            frame, model, analyst, "product", Category.PRODUCT, "category"
        ),
    )
    run(
        "regional performance",
        lambda: _dimension_insights(
            frame, model, analyst, "region", Category.REGION, "region"
        ),
    )

    try:
        seasonal, seasonal_skipped = detect_seasonality(frame, model)
        found.extend(seasonal)
        skipped.extend(seasonal_skipped)
    except Exception:
        logger.exception("Seasonality detection failed")
        skipped.append(
            {"analysis": "seasonality", "reason": "Seasonality could not be computed."}
        )

    try:
        customer_found, customer_skipped, segments = detect_customers(customers)
        found.extend(customer_found)
        skipped.extend(customer_skipped)
    except Exception:
        logger.exception("Customer insight detection failed")
        skipped.append(
            {
                "analysis": "customer insights",
                "reason": "Customer analysis could not be computed from this dataset.",
            }
        )

    # Highest priority first; ties broken by severity so the ordering is stable.
    severity_rank = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
        Severity.INFO: 4,
    }
    found.sort(key=lambda item: (-item.priority_score, severity_rank[item.severity], item.id))
    return found, skipped, segments


# --- Recommendations ---------------------------------------------------------

#: What acting on a finding of each kind could plausibly improve. Always framed
#: as a possibility - no financial outcome is ever guaranteed.
_IMPACT_BY_CATEGORY: dict[InsightCategory, str] = {
    Category.PERFORMANCE: "Potential impact: sustaining or recovering a headline measure.",
    Category.OPPORTUNITY: (
        "Potential impact: additional revenue from an area already performing well."
    ),
    Category.RISK: "Potential impact: avoiding further loss if the trend continues unaddressed.",
    Category.TREND: (
        "Potential impact: better planning against a pattern already present in the data."
    ),
    Category.CUSTOMER: "Potential impact: improved retention and repeat purchase value.",
    Category.PRODUCT: "Potential impact: a better-balanced category mix.",
    Category.REGION: "Potential impact: recovered or extended regional performance.",
    Category.OPERATIONS: (
        "Potential impact: fewer poor delivery experiences and better satisfaction."
    ),
    Category.DATA_QUALITY: (
        "Potential impact: more reliable figures, and more confidence in every other "
        "finding on this page."
    ),
}

#: Recommendations offered per run. Beyond this the list stops being a plan.
MAX_RECOMMENDATIONS = 10


def build_recommendations(insights: Sequence[BusinessInsight]) -> list[Recommendation]:
    """Turn actionable findings into a ranked plan.

    Only insights that carry an action become recommendations, so nothing here
    is generic advice - each one points back at the finding that justifies it.
    """
    recommendations: list[Recommendation] = []
    seen: set[str] = set()

    for insight in insights:
        action = insight.action or insight.recommendation
        if not action or action in seen:
            continue
        seen.add(action)

        recommendations.append(
            Recommendation(
                id=f"rec-{insight.id}",
                title=insight.title,
                action=action,
                reason=insight.summary,
                supporting_insight_ids=[insight.id],
                expected_impact=_IMPACT_BY_CATEGORY.get(
                    insight.category, "Potential impact: an improvement in this area."
                ),
                priority=insight.priority,
                category=insight.category,
            )
        )
        if len(recommendations) >= MAX_RECOMMENDATIONS:
            break

    return recommendations


def summarise(
    frame: pd.DataFrame,
    insights: Sequence[BusinessInsight],
    health_score: int | None,
) -> str:
    """The deterministic answer to "what should the business owner know?"."""
    parts = [
        f"This dataset covers {len(frame):,} records across {len(frame.columns)} columns."
    ]
    if health_score is not None:
        parts.append(f"Overall business health scores {health_score}/100.")

    urgent = [
        item
        for item in insights
        if item.priority in (Priority.CRITICAL, Priority.HIGH)
    ]
    risks = [item for item in insights if item.category is Category.RISK]
    opportunities = [item for item in insights if item.category is Category.OPPORTUNITY]

    if urgent:
        parts.append(
            f"{len(urgent)} finding(s) need attention first, starting with: {urgent[0].title}."
        )
    if risks:
        parts.append(f"{len(risks)} potential risk(s) were detected.")
    if opportunities:
        parts.append(
            f"{len(opportunities)} opportunit{'y' if len(opportunities) == 1 else 'ies'} "
            f"were identified, including: {opportunities[0].title}."
        )
    if not insights:
        parts.append(
            "No findings crossed the detection thresholds - the measures in this "
            "dataset are stable or there is not enough history to judge them."
        )

    return " ".join(parts)
