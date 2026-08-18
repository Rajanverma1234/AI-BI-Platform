"""Business health score.

The score is a weighted mean of seven measurable signals. It is deliberately
arithmetic rather than a model, because the page has to be able to answer "how
is this calculated?" with the actual numbers.

Three properties make it honest:

- A signal that cannot be measured is *excluded*, not scored zero. Weights are
  renormalised across whatever remains, so a dataset with no ratings is not
  punished for lacking a column it never had.
- If nothing at all is measurable the score is ``None`` and the rating is
  ``unknown``. There is no fallback number.
- Every factor carries the evidence it was derived from, so a score can be
  taken apart back to the figures that produced it.

Inputs come from services that have already run: trends from the analyst
report, churn and RFM from the shared customer analytics, anomalies from the
analyst's outlier detection. Only the order and customer volume series are
computed here, and both go through the existing ``analytics_engine``.
"""

from __future__ import annotations

import pandas as pd

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.schemas.ai_analyst import AnalystReport, TrendDirection
from app.schemas.analytics import GrowthRequest, MetricType
from app.schemas.insights import (
    BusinessHealth,
    Evidence,
    FactorStatus,
    HealthFactor,
    HealthRating,
)
from app.services import analytics_engine, insight_engine
from app.services.business_insight_engine import (
    CustomerAnalytics,
    evidence,
    text_evidence,
)
from app.services.semantic_columns import SemanticModel

logger = get_logger(__name__)

#: Relative importance of each signal, before renormalisation over the ones
#: that could actually be measured.
WEIGHTS: dict[str, float] = {
    "revenue_trend": 0.25,
    "order_trend": 0.15,
    "customer_trend": 0.15,
    "churn": 0.15,
    "rating_trend": 0.10,
    "operations": 0.10,
    "anomalies": 0.10,
}

FACTOR_NAMES: dict[str, str] = {
    "revenue_trend": "Revenue trend",
    "order_trend": "Order volume trend",
    "customer_trend": "Customer trend",
    "churn": "Customer retention",
    "rating_trend": "Rating trend",
    "operations": "Operational performance",
    "anomalies": "Anomaly level",
}

METHODOLOGY = (
    "Each signal below is scored 0-100 from measured figures, then combined as a "
    "weighted average. Signals this dataset cannot support are excluded and the "
    "remaining weights are rescaled to sum to 100%, so a missing column never "
    "counts as a zero. A score is only shown when at least one signal could be "
    "measured."
)

#: Percentage-change thresholds shared by every trend-based factor.
_STRONG_GROWTH = 20.0
_MILD_GROWTH = 5.0
_MILD_DECLINE = -5.0
_SHARP_DECLINE = -20.0


def _score_from_change(change: float | None, *, higher_is_better: bool = True) -> float:
    """Map a percentage change onto 0-100 using fixed, published bands."""
    if change is None:
        return 50.0
    value = change if higher_is_better else -change
    if value >= _STRONG_GROWTH:
        return 100.0
    if value >= _MILD_GROWTH:
        return 80.0
    if value >= _MILD_DECLINE:
        return 60.0
    if value >= _SHARP_DECLINE:
        return 35.0
    return 10.0


def _status_for(score: float) -> FactorStatus:
    if score >= 70:
        return FactorStatus.POSITIVE
    if score >= 45:
        return FactorStatus.MODERATE
    return FactorStatus.NEGATIVE


def _trend_factor(
    key: str,
    analyst: AnalystReport,
    column: str | None,
    *,
    higher_is_better: bool = True,
) -> HealthFactor | None:
    """Score one of the analyst's existing trends, if it produced a direction."""
    if not column:
        return None
    trend = next((item for item in analyst.trends if item.metric_column == column), None)
    if trend is None or trend.direction is TrendDirection.INSUFFICIENT_DATA:
        return None
    if trend.percentage_change is None:
        return None

    score = _score_from_change(trend.percentage_change, higher_is_better=higher_is_better)
    direction = trend.direction.value
    return HealthFactor(
        key=key,
        name=FACTOR_NAMES[key],
        status=_status_for(score),
        score=score,
        detail=(
            f"{column} is {direction} - {trend.percentage_change:+.1f}% from "
            f"{trend.first_label} to {trend.last_label} across "
            f"{trend.periods_observed} {trend.period.value} periods."
        ),
        evidence=[
            evidence(f"{column} ({trend.last_label})", trend.last_value),
            evidence(f"{column} ({trend.first_label})", trend.first_value),
            evidence("Change", trend.percentage_change, suffix="%"),
            evidence("Periods observed", float(trend.periods_observed)),
        ],
    )


def _volume_factor(
    key: str,
    frame: pd.DataFrame,
    model: SemanticModel,
    metric: MetricType,
    column: str | None,
    noun: str,
) -> HealthFactor | None:
    """Score the growth of a per-period count using the existing growth engine."""
    date_column = model.get("date")
    if not date_column:
        return None
    if metric is MetricType.DISTINCT_COUNT and not column:
        return None

    try:
        growth = analytics_engine.build_growth(
            frame,
            GrowthRequest(
                date_column=date_column,
                period=insight_engine._choose_period(frame, date_column),
                metric=metric,
                column=column,
            ),
        )
    except AppError as exc:
        logger.info("Health factor %s skipped: %s", key, exc.message)
        return None

    points = [point for point in growth.points if point.value is not None]
    if len(points) < insight_engine.MIN_TREND_PERIODS:
        return None

    first, last = points[0], points[-1]
    if not first.value:
        return None

    change = ((last.value or 0) - first.value) / first.value * 100
    score = _score_from_change(change)
    return HealthFactor(
        key=key,
        name=FACTOR_NAMES[key],
        status=_status_for(score),
        score=score,
        detail=(
            f"{noun} moved {change:+.1f}% from {first.label} ({first.value:,.0f}) to "
            f"{last.label} ({(last.value or 0):,.0f})."
        ),
        evidence=[
            evidence(f"{noun} ({last.label})", last.value),
            evidence(f"{noun} ({first.label})", first.value),
            evidence("Change", change, suffix="%"),
            evidence("Periods observed", float(len(points))),
        ],
    )


def _churn_factor(customers: CustomerAnalytics) -> HealthFactor | None:
    """Retention scored directly from the churn rate already computed."""
    churn = customers.churn
    if churn is None or not churn.get("total_customers"):
        return None

    rate = float(churn["churn_rate"])
    # A linear read of the rate: 0% churn scores 100, 50%+ scores 0.
    score = max(0.0, min(100.0, 100.0 - rate * 2))
    return HealthFactor(
        key="churn",
        name=FACTOR_NAMES["churn"],
        status=_status_for(score),
        score=round(score, 1),
        detail=(
            f"{churn['active_customers']:,} of {churn['total_customers']:,} customers "
            f"are active within 90 days, a churn rate of {rate:.1f}%."
        ),
        evidence=[
            evidence("Churn rate", rate, suffix="%"),
            evidence("Active customers", float(churn["active_customers"])),
            evidence("At-risk customers", float(churn["at_risk_customers"])),
            evidence("Churned customers", float(churn["churned_customers"])),
            text_evidence("Measured against", str(churn["reference_date"])),
        ],
    )


def _operations_factor(
    analyst: AnalystReport, model: SemanticModel
) -> HealthFactor | None:
    """Delivery performance, where lower is better."""
    delivery = model.get("delivery")
    factor = _trend_factor("operations", analyst, delivery, higher_is_better=False)
    if factor is None:
        return None
    factor.detail = (
        f"{factor.detail} Shorter {delivery} is treated as better, so a falling "
        "trend scores higher."
    )
    return factor


def _anomaly_factor(analyst: AnalystReport) -> HealthFactor | None:
    """How much of the data sits outside the expected range."""
    if not analyst.anomalies:
        return None

    worst = max(item.outlier_percentage for item in analyst.anomalies)
    total = sum(item.outlier_count for item in analyst.anomalies)
    # 0% outliers scores 100; 10% or more of a column outlying scores 0.
    score = max(0.0, min(100.0, 100.0 - worst * 10))
    return HealthFactor(
        key="anomalies",
        name=FACTOR_NAMES["anomalies"],
        status=_status_for(score),
        score=round(score, 1),
        detail=(
            f"The most affected measure has {worst:.2f}% of its values outside the "
            f"expected range, across {len(analyst.anomalies)} measure(s) checked."
        ),
        evidence=[
            evidence("Highest outlier share", worst, suffix="%"),
            evidence("Measures checked", float(len(analyst.anomalies))),
            evidence("Total values flagged", float(total)),
        ]
        + [
            text_evidence(item.metric_column, f"{item.outlier_percentage:.2f}% outlying")
            for item in analyst.anomalies[:5]
        ],
    )


def _rating_for(score: int) -> HealthRating:
    if score >= 80:
        return HealthRating.STRONG
    if score >= 65:
        return HealthRating.HEALTHY
    if score >= 45:
        return HealthRating.MIXED
    return HealthRating.AT_RISK


def _excluded_reason(key: str, model: SemanticModel) -> str:
    """Say what the dataset would need for this signal to be scored."""
    reasons = {
        "revenue_trend": "a monetary column and a date column with enough history",
        "order_trend": "a date column with at least three periods of history",
        "customer_trend": "a customer identifier and a date column",
        "churn": "a customer identifier and a transaction date",
        "rating_trend": "a rating or satisfaction column and a date column",
        "operations": "a delivery or lead-time column and a date column",
        "anomalies": "at least one numeric measure with varying values",
    }
    return f"{FACTOR_NAMES[key]} needs {reasons[key]}. This dataset does not provide it."


def evaluate(
    frame: pd.DataFrame,
    model: SemanticModel,
    analyst: AnalystReport,
    customers: CustomerAnalytics,
) -> BusinessHealth:
    """Score overall business health from the signals this dataset supports."""
    candidates: dict[str, HealthFactor | None] = {
        "revenue_trend": _trend_factor("revenue_trend", analyst, model.get("revenue")),
        "order_trend": _volume_factor(
            "order_trend", frame, model, MetricType.COUNT, None, "Record volume"
        ),
        "customer_trend": _volume_factor(
            "customer_trend",
            frame,
            model,
            MetricType.DISTINCT_COUNT,
            model.get("customer"),
            "Active customers",
        ),
        "churn": _churn_factor(customers),
        "rating_trend": _trend_factor("rating_trend", analyst, model.get("rating")),
        "operations": _operations_factor(analyst, model),
        "anomalies": _anomaly_factor(analyst),
    }

    measured = {key: factor for key, factor in candidates.items() if factor is not None}
    excluded = [
        {"factor": FACTOR_NAMES[key], "reason": _excluded_reason(key, model)}
        for key in WEIGHTS
        if key not in measured
    ]

    if not measured:
        return BusinessHealth(
            score=None,
            rating=HealthRating.UNKNOWN,
            methodology=METHODOLOGY,
            factors=[],
            excluded=excluded,
        )

    # Renormalise so the measurable signals carry the whole score between them.
    total_weight = sum(WEIGHTS[key] for key in measured)
    factors: list[HealthFactor] = []
    weighted_sum = 0.0
    for key, factor in measured.items():
        share = WEIGHTS[key] / total_weight
        factor.weight = round(share, 4)
        weighted_sum += (factor.score or 0.0) * share
        factors.append(factor)

    # Worst signals first: the page should open with what needs attention.
    factors.sort(key=lambda item: item.score or 0.0)
    score = int(round(weighted_sum))

    return BusinessHealth(
        score=score,
        rating=_rating_for(score),
        methodology=METHODOLOGY,
        factors=factors,
        excluded=excluded,
    )


def health_evidence(health: BusinessHealth) -> list[Evidence]:
    """Flatten a health result into evidence rows, for reports and the AI context."""
    return [
        Evidence(
            label=factor.name,
            value=factor.score,
            formatted=f"{factor.score:.0f}/100" if factor.score is not None else "n/a",
            detail=f"{factor.weight * 100:.0f}% of the score - {factor.detail}",
        )
        for factor in health.factors
    ]
