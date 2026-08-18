"""Business insight detection and health scoring.

The properties worth protecting are the honesty ones: a finding is only made
when the data supports it, a measure whose polarity is inverted (delivery time)
is not reported as a decline, the health score excludes what it cannot measure
instead of scoring it zero, and every insight carries the evidence behind it.
"""

from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest

from app.models.dataset import Dataset, DatasetFileType, DatasetStatus
from app.schemas.insights import (
    FactorStatus,
    HealthRating,
    InsightCategory,
    InsightPriority,
    InsightSeverity,
)
from app.services import (
    ai_analyst_service,
    data_quality,
    dataset_access,
    dataset_profiling,
    insights_service,
    semantic_columns,
)
from app.services import business_insight_engine as detector

ROWS = 900
Category = InsightCategory
Severity = InsightSeverity
Priority = InsightPriority


def make_loaded(frame: pd.DataFrame) -> dataset_access.LoadedDataset:
    dataset = Dataset(
        id=uuid.uuid4(),
        name="Sales export",
        original_filename="sales.csv",
        storage_key="datasets/test/data.csv",
        file_type=DatasetFileType.CSV,
        file_size=1,
        status=DatasetStatus.READY,
        project_id=uuid.uuid4(),
    )
    return dataset_access.LoadedDataset(dataset=dataset, frame=frame, version=None)


def build(frame: pd.DataFrame):
    """The same path the service takes, without database or storage."""
    loaded = make_loaded(frame)
    profile = dataset_profiling.profile_frame(frame, dataset_id=loaded.dataset.id)
    quality = data_quality.assess_quality(profile, frame, dataset_id=loaded.dataset.id)
    analyst = ai_analyst_service.build_report(frame, loaded, profile=profile, quality=quality)
    return insights_service.build_deterministic(
        frame,
        loaded,
        analyst,
        quality,
        project_id=loaded.dataset.project_id,
        generated_by="Test User",
    )


@pytest.fixture
def declining_frame() -> pd.DataFrame:
    """A business in trouble: revenue falling, ratings slipping, delivery improving."""
    rng = np.random.default_rng(7)
    regions = rng.choice(["North", "South", "East", "West"], ROWS, p=[0.4, 0.3, 0.2, 0.1])
    decline = np.linspace(1.0, 0.5, ROWS)
    return pd.DataFrame(
        {
            "order_id": range(1, ROWS + 1),
            "customer_id": rng.integers(1000, 1150, ROWS),
            "category": rng.choice(
                ["Electronics", "Grocery", "Apparel"], ROWS, p=[0.6, 0.25, 0.15]
            ),
            "region": regions,
            "total_amount": np.round(rng.gamma(4, 60, ROWS) * decline, 2),
            "quantity": rng.integers(1, 6, ROWS),
            "discount_pct": np.round(np.abs(rng.normal(8, 6, ROWS)), 2),
            "rating": np.round(
                np.clip(rng.normal(4.3, 0.5, ROWS) - np.linspace(0, 0.9, ROWS), 1, 5), 1
            ),
            "delivery_days": np.round(
                np.abs(rng.normal(4, 1.5, ROWS)) - np.linspace(0, 1.5, ROWS) + 2, 1
            ),
            "order_date": pd.date_range("2023-01-01", periods=ROWS, freq="12h"),
        }
    )


@pytest.fixture
def bare_frame() -> pd.DataFrame:
    """No dates, no customers, one measure - almost nothing is detectable."""
    return pd.DataFrame(
        {
            "label": [f"item-{index % 6}" for index in range(60)],
            "score": [float(index % 9) for index in range(60)],
        }
    )


def by_id(report, prefix: str):
    return [item for item in report.insights if item.id.startswith(prefix)]


# --- Detection ---------------------------------------------------------------


def test_declining_revenue_is_reported_as_a_hedged_risk(declining_frame: pd.DataFrame) -> None:
    report = build(declining_frame)
    risks = [item for item in report.insights if item.category is Category.RISK]

    assert risks, "a dataset with halving revenue produced no risk"
    revenue_risk = next(item for item in risks if item.metric == "total_amount")
    assert revenue_risk.percentage_change is not None
    assert revenue_risk.percentage_change < 0
    # Hedged wording: a decline is detected, its cause is not claimed.
    assert "potential risk" in revenue_risk.summary.lower()
    assert "because" not in revenue_risk.summary.lower()


def test_every_insight_carries_its_evidence(declining_frame: pd.DataFrame) -> None:
    report = build(declining_frame)

    assert report.insights
    for insight in report.insights:
        assert insight.evidence, f"{insight.id} has no evidence to explain it"
        assert insight.source
        assert insight.priority_reason
        for item in insight.evidence:
            assert item.formatted


def test_improving_delivery_time_is_not_called_a_decline(
    declining_frame: pd.DataFrame,
) -> None:
    """Delivery time is inverted: shorter is better, so a fall is good news."""
    report = build(declining_frame)
    delivery = [item for item in report.insights if item.metric == "delivery_days"]

    assert delivery, "the delivery trend was not reported at all"
    trend = next(item for item in delivery if item.id == "operations-delivery-trend")
    assert trend.percentage_change is not None and trend.percentage_change < 0
    assert trend.category is Category.OPERATIONS
    assert trend.severity is Severity.INFO
    assert "improving" in trend.title


def test_rating_decline_is_reported_once_by_operations(
    declining_frame: pd.DataFrame,
) -> None:
    """Operations owns rating; performance must not report the same trend again."""
    report = build(declining_frame)
    rating = [item for item in report.insights if item.metric == "rating"]

    assert len(rating) == 1
    assert rating[0].category is Category.OPERATIONS


def test_opportunities_state_what_why_and_action(declining_frame: pd.DataFrame) -> None:
    report = build(declining_frame)
    opportunities = [
        item for item in report.insights if item.category is Category.OPPORTUNITY
    ]

    assert opportunities
    for item in opportunities:
        assert item.title  # WHAT
        assert item.why  # WHY
        assert item.evidence  # EVIDENCE
        assert item.action  # ACTION


def test_nothing_is_detected_without_the_supporting_columns(
    bare_frame: pd.DataFrame,
) -> None:
    report = build(bare_frame)

    # No date column, so nothing time-based can be claimed.
    assert not [item for item in report.insights if item.category is Category.TREND]
    assert not [item for item in report.insights if item.metric == "churn_rate"]
    # And the reason is stated rather than left silent.
    assert any("customer" in item["analysis"].lower() for item in report.skipped)


def test_seasonality_needs_two_years_before_it_is_claimed(
    declining_frame: pd.DataFrame,
) -> None:
    """The fixture spans about 15 months, which is not enough."""
    report = build(declining_frame)

    assert not by_id(report, "seasonality-")
    reason = next(
        item["reason"] for item in report.skipped if item["analysis"] == "seasonality"
    )
    assert str(detector.MIN_MONTHS_FOR_SEASONALITY) in reason


def test_seasonality_is_detected_with_enough_history() -> None:
    rng = np.random.default_rng(3)
    periods = 365 * 3
    dates = pd.date_range("2021-01-01", periods=periods, freq="D")
    # A deliberate December lift, repeated across three years.
    lift = np.where(dates.month == 12, 2.2, 1.0)
    frame = pd.DataFrame(
        {
            "order_id": range(1, periods + 1),
            "total_amount": np.round(rng.gamma(4, 50, periods) * lift, 2),
            "order_date": dates,
        }
    )

    report = build(frame)
    seasonal = by_id(report, "seasonality-")

    assert seasonal, "three years with a December spike produced no seasonal finding"
    assert seasonal[0].dimension_value == "December"
    assert seasonal[0].percentage_change is not None


# --- Prioritisation ----------------------------------------------------------


def test_priority_rises_with_severity_magnitude_and_coverage() -> None:
    low, low_score, _ = detector.priority_for(Severity.LOW)
    high, high_score, reason = detector.priority_for(
        Severity.HIGH, magnitude_pct=-45.0, coverage=0.8, persistence_periods=12
    )

    assert low is Priority.LOW
    assert high_score > low_score
    assert high in (Priority.HIGH, Priority.CRITICAL)
    # The ranking must be explainable, not a black box.
    assert "severity high" in reason
    assert "magnitude" in reason and "covers" in reason


def test_insights_are_returned_highest_priority_first(
    declining_frame: pd.DataFrame,
) -> None:
    report = build(declining_frame)
    scores = [item.priority_score for item in report.insights]

    assert scores == sorted(scores, reverse=True)


def test_counts_match_the_insights(declining_frame: pd.DataFrame) -> None:
    report = build(declining_frame)

    assert sum(report.counts_by_category.values()) == len(report.insights)
    assert sum(report.counts_by_severity.values()) == len(report.insights)
    assert sum(report.counts_by_priority.values()) == len(report.insights)


# --- Business health ---------------------------------------------------------


def test_health_score_is_a_weighted_mean_of_its_factors(
    declining_frame: pd.DataFrame,
) -> None:
    report = build(declining_frame)
    health = report.health

    assert health.score is not None
    assert health.factors
    # Weights are renormalised over the factors that could be measured.
    assert sum(factor.weight for factor in health.factors) == pytest.approx(1.0, abs=0.01)
    expected = sum((factor.score or 0) * factor.weight for factor in health.factors)
    assert health.score == pytest.approx(expected, abs=0.5)


def test_declining_business_scores_as_at_risk(declining_frame: pd.DataFrame) -> None:
    health = build(declining_frame).health

    assert health.score is not None and health.score < 50
    assert health.rating is HealthRating.AT_RISK
    assert any(factor.status is FactorStatus.NEGATIVE for factor in health.factors)


def test_unmeasurable_factors_are_excluded_not_scored_zero(
    bare_frame: pd.DataFrame,
) -> None:
    health = build(bare_frame).health

    assert health.excluded, "a dataset with no dates excluded nothing"
    for item in health.excluded:
        assert item["reason"].strip()
    # Anything excluded must not appear as a scored factor.
    scored = {factor.name for factor in health.factors}
    assert not scored & {item["factor"] for item in health.excluded}


def test_no_measurable_signal_gives_no_score_rather_than_a_guess() -> None:
    frame = pd.DataFrame({"label": ["a", "b", "c"], "note": ["x", "y", "z"]})
    health = build(frame).health

    assert health.score is None
    assert health.rating is HealthRating.UNKNOWN
    assert health.methodology


def test_health_methodology_is_always_present(declining_frame: pd.DataFrame) -> None:
    health = build(declining_frame).health

    assert "weighted average" in health.methodology
    assert "rescaled" in health.methodology


# --- Recommendations ---------------------------------------------------------


def test_recommendations_are_tied_to_findings_and_hedge_their_impact(
    declining_frame: pd.DataFrame,
) -> None:
    report = build(declining_frame)

    assert report.recommendations
    insight_ids = {item.id for item in report.insights}
    for recommendation in report.recommendations:
        assert recommendation.supporting_insight_ids
        assert set(recommendation.supporting_insight_ids) <= insight_ids
        assert recommendation.expected_impact.startswith("Potential impact")
        assert recommendation.action


def test_recommendations_are_capped_and_deduplicated(
    declining_frame: pd.DataFrame,
) -> None:
    report = build(declining_frame)
    actions = [item.action for item in report.recommendations]

    assert len(actions) == len(set(actions))
    assert len(actions) <= detector.MAX_RECOMMENDATIONS


# --- Filters and context -----------------------------------------------------


def test_filters_come_from_the_dataset_not_a_fixed_list(
    declining_frame: pd.DataFrame,
) -> None:
    report = build(declining_frame)

    assert set(report.filters.regions) == {"North", "South", "East", "West"}
    assert set(report.filters.products) == {"Electronics", "Grocery", "Apparel"}
    assert report.filters.region_column == "region"
    assert report.filters.periods
    # Only the categories actually present in this run are offered.
    assert set(report.filters.categories) == {
        item.category for item in report.insights
    }


def test_ai_context_carries_no_raw_rows(declining_frame: pd.DataFrame) -> None:
    from app.schemas.insights import build_context_payload

    report = build(declining_frame)
    context = build_context_payload(report)

    assert set(context) == {
        "dataset",
        "business_health",
        "insights",
        "recommendations",
        "supporting_metrics",
    }
    # The compact context is orders of magnitude smaller than the data.
    assert len(str(context)) < 200_000
    assert "customer_id" not in str(context.get("dataset"))


def test_report_is_deterministic_without_an_ai_provider(
    declining_frame: pd.DataFrame,
) -> None:
    report = build(declining_frame)

    assert report.ai is None
    assert report.ai_available is False
    assert report.summary.strip()
    assert report.insights
    assert report.analysis_version == detector.ANALYSIS_VERSION


def test_semantic_roles_drive_detection_not_column_names() -> None:
    """The same data under different names must still be analysed."""
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {
            "txn_ref": range(1, 400),
            "buyer_account": rng.integers(1, 60, 399),
            "net_amount": np.round(rng.gamma(4, 40, 399) * np.linspace(1, 0.6, 399), 2),
            "booking_date": pd.date_range("2023-01-01", periods=399, freq="D"),
        }
    )

    model = semantic_columns.detect(frame)
    assert model.get("revenue") == "net_amount"

    report = build(frame)
    assert report.insights
    assert report.health.score is not None
