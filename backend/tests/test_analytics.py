"""KPI engine tests, focused on the measure-vs-identifier distinction."""

from __future__ import annotations

import uuid

import pandas as pd
import pytest

from app.core.exceptions import ValidationError
from app.schemas.analytics import (
    AbcRequest,
    BinaryNode,
    BinaryOperator,
    ColumnRole,
    ConstantNode,
    GrowthRequest,
    KpiDefinition,
    MetricRef,
    MetricType,
    SegmentRequest,
    TimePeriod,
    TimeSeriesRequest,
)
from app.services import analytics_engine
from app.services.analytics_service import evaluate_kpi

ROWS = 200


@pytest.fixture
def sales_frame() -> pd.DataFrame:
    """Mirrors a typical e-commerce export: ids, measures, a category, a date."""
    return pd.DataFrame(
        {
            # Unique per row and id-named: a key, not a measure.
            "order_id": range(1, ROWS + 1),
            # Id-named but repeating: still a key.
            "customer_id": [1000 + (index % 40) for index in range(ROWS)],
            # Float, nearly unique per row - a measure, despite high cardinality.
            "revenue": [round(10.5 + index * 1.37, 2) for index in range(ROWS)],
            # Small-range integer measure.
            "quantity": [(index % 5) + 1 for index in range(ROWS)],
            "region": ["North", "South", "East", "West"][0:1] * ROWS,
            "category": [["Electronics", "Grocery", "Apparel"][index % 3] for index in range(ROWS)],
            "order_date": pd.date_range("2026-01-01", periods=ROWS, freq="D"),
        }
    )


def roles_by_name(frame: pd.DataFrame) -> dict[str, ColumnRole]:
    return {role.name: role for role in analytics_engine.describe_columns(frame)}


# --- Column roles ------------------------------------------------------------


def test_id_named_column_is_an_identifier_not_a_measure(sales_frame: pd.DataFrame) -> None:
    roles = roles_by_name(sales_frame)

    assert roles["order_id"].numeric is True
    assert roles["order_id"].identifier is True
    # The bug this guards: SUM(order_id) was being offered as a KPI.
    assert roles["order_id"].measure is False


def test_repeating_id_column_is_still_an_identifier(sales_frame: pd.DataFrame) -> None:
    roles = roles_by_name(sales_frame)

    assert roles["customer_id"].identifier is True
    assert roles["customer_id"].measure is False


def test_high_cardinality_float_is_a_measure(sales_frame: pd.DataFrame) -> None:
    """A revenue column is often unique per row; that must not make it a key."""
    roles = roles_by_name(sales_frame)

    assert roles["revenue"].measure is True
    assert roles["revenue"].identifier is False


def test_small_range_integer_is_a_measure(sales_frame: pd.DataFrame) -> None:
    roles = roles_by_name(sales_frame)

    assert roles["quantity"].measure is True
    assert roles["quantity"].identifier is False


def test_low_cardinality_text_is_a_dimension(sales_frame: pd.DataFrame) -> None:
    roles = roles_by_name(sales_frame)

    assert roles["category"].categorical is True
    assert roles["category"].measure is False


def test_date_column_is_temporal_and_not_an_identifier(sales_frame: pd.DataFrame) -> None:
    """Dates are unique per row here, but a time axis is not a key."""
    role = roles_by_name(sales_frame)["order_date"]

    assert role.temporal is True
    assert role.identifier is False
    assert role.measure is False


# --- Metrics -----------------------------------------------------------------


def test_count_without_a_column_counts_rows(sales_frame: pd.DataFrame) -> None:
    assert analytics_engine.compute_metric(sales_frame, MetricType.COUNT, None) == float(ROWS)


def test_distinct_count_counts_unique_values(sales_frame: pd.DataFrame) -> None:
    assert analytics_engine.compute_metric(
        sales_frame, MetricType.DISTINCT_COUNT, "customer_id"
    ) == 40.0


def test_sum_rejects_a_non_numeric_column(sales_frame: pd.DataFrame) -> None:
    with pytest.raises(ValidationError, match="needs a numeric column"):
        analytics_engine.compute_metric(sales_frame, MetricType.SUM, "category")


def test_unknown_column_is_rejected(sales_frame: pd.DataFrame) -> None:
    with pytest.raises(ValidationError, match="Unknown column"):
        analytics_engine.compute_metric(sales_frame, MetricType.SUM, "not_a_column")


def test_std_dev_is_undefined_for_a_single_row() -> None:
    frame = pd.DataFrame({"value": [5.0]})

    assert analytics_engine.compute_metric(frame, MetricType.STD_DEV, "value") is None


def test_metrics_ignore_nulls() -> None:
    frame = pd.DataFrame({"value": [10.0, None, 20.0]})

    assert analytics_engine.compute_metric(frame, MetricType.SUM, "value") == 30.0
    assert analytics_engine.compute_metric(frame, MetricType.AVERAGE, "value") == 15.0


# --- Formula engine ----------------------------------------------------------


def test_formula_computes_a_ratio(sales_frame: pd.DataFrame) -> None:
    formula = BinaryNode(
        operator=BinaryOperator.DIVIDE,
        left=MetricRef(metric=MetricType.SUM, column="revenue"),
        right=MetricRef(metric=MetricType.DISTINCT_COUNT, column="customer_id"),
    )

    total = analytics_engine.compute_metric(sales_frame, MetricType.SUM, "revenue")
    result = analytics_engine.evaluate_formula(sales_frame, formula)

    assert result == pytest.approx((total or 0) / 40)


def test_formula_returns_none_on_division_by_zero() -> None:
    frame = pd.DataFrame({"value": [5.0], "zero": [0.0]})
    formula = BinaryNode(
        operator=BinaryOperator.DIVIDE,
        left=MetricRef(metric=MetricType.SUM, column="value"),
        right=MetricRef(metric=MetricType.SUM, column="zero"),
    )

    assert analytics_engine.evaluate_formula(frame, formula) is None


def test_formula_scales_to_a_percentage(sales_frame: pd.DataFrame) -> None:
    ratio = BinaryNode(
        operator=BinaryOperator.DIVIDE,
        left=MetricRef(metric=MetricType.SUM, column="quantity"),
        right=MetricRef(metric=MetricType.COUNT, column=None),
    )
    formula = BinaryNode(
        operator=BinaryOperator.MULTIPLY, left=ratio, right=ConstantNode(value=100)
    )

    average = analytics_engine.compute_metric(sales_frame, MetricType.AVERAGE, "quantity")
    assert analytics_engine.evaluate_formula(sales_frame, formula) == pytest.approx(
        (average or 0) * 100
    )


# --- KPI evaluation ----------------------------------------------------------


def test_kpi_reports_a_missing_column_instead_of_failing(sales_frame: pd.DataFrame) -> None:
    result = evaluate_kpi(
        sales_frame,
        KpiDefinition(name="Broken", metric=MetricType.SUM, column="missing_column"),
    )

    assert result.available is False
    assert result.value is None
    assert "Unknown column" in (result.reason or "")


def test_kpi_without_metric_or_formula_is_unavailable(sales_frame: pd.DataFrame) -> None:
    result = evaluate_kpi(sales_frame, KpiDefinition(name="Empty"))

    assert result.available is False


def test_kpi_computes_a_comparison(sales_frame: pd.DataFrame) -> None:
    result = evaluate_kpi(
        sales_frame,
        KpiDefinition(
            name="Monthly revenue",
            metric=MetricType.SUM,
            column="revenue",
            comparison={"date_column": "order_date", "period": TimePeriod.MONTH},
        ),
    )

    assert result.available is True
    assert result.comparison is not None
    assert result.comparison.previous_value is not None


# --- Analyses ----------------------------------------------------------------


def test_time_series_groups_by_month(sales_frame: pd.DataFrame) -> None:
    result = analytics_engine.build_time_series(
        sales_frame,
        TimeSeriesRequest(
            date_column="order_date",
            period=TimePeriod.MONTH,
            metric=MetricType.SUM,
            column="revenue",
        ),
    )

    # 200 daily rows from 2026-01-01 spans seven calendar months.
    assert len(result.labels) == 7
    assert result.labels[0] == "2026-01"


def test_growth_reports_insufficient_history() -> None:
    frame = pd.DataFrame({"when": pd.to_datetime(["2026-01-05"]), "value": [10.0]})

    result = analytics_engine.build_growth(
        frame,
        GrowthRequest(
            date_column="when",
            period=TimePeriod.MONTH,
            metric=MetricType.SUM,
            column="value",
        ),
    )

    assert result.message is not None
    assert "At least two" in result.message


def test_time_series_rejects_a_non_date_column(sales_frame: pd.DataFrame) -> None:
    with pytest.raises(ValidationError, match="recognisable dates"):
        analytics_engine.build_time_series(
            sales_frame,
            TimeSeriesRequest(date_column="category", metric=MetricType.COUNT),
        )


def test_segment_percentages_use_the_overall_total(sales_frame: pd.DataFrame) -> None:
    result = analytics_engine.build_segment(
        sales_frame,
        SegmentRequest(dimension="category", metric=MetricType.SUM, column="revenue"),
    )

    assert result.group_count == 3
    assert sum(row.percentage or 0 for row in result.rows) == pytest.approx(100.0, abs=0.01)


def test_contribution_accumulates_to_100_percent(sales_frame: pd.DataFrame) -> None:
    result = analytics_engine.build_contribution(
        sales_frame,
        SegmentRequest(dimension="category", metric=MetricType.SUM, column="revenue"),
    )

    assert result.rows[-1].cumulative_percentage == pytest.approx(100.0, abs=0.01)


def test_abc_classifies_and_summarises(sales_frame: pd.DataFrame) -> None:
    result = analytics_engine.build_abc(
        sales_frame,
        AbcRequest(dimension="category", metric=MetricType.SUM, column="revenue"),
    )

    assert {row.abc_class for row in result.rows} <= {"A", "B", "C"}
    assert sum(item.item_count for item in result.summary) == len(result.rows)


def test_abc_rejects_inverted_thresholds(sales_frame: pd.DataFrame) -> None:
    with pytest.raises(ValidationError, match="B threshold"):
        analytics_engine.build_abc(
            sales_frame,
            AbcRequest(
                dimension="category",
                metric=MetricType.SUM,
                column="revenue",
                a_threshold=90,
                b_threshold=80,
            ),
        )


def test_entity_analysis_splits_repeat_and_one_time(sales_frame: pd.DataFrame) -> None:
    from app.schemas.analytics import EntityRequest

    result = analytics_engine.build_entity_analysis(
        sales_frame,
        EntityRequest(entity_column="customer_id", value_column="revenue"),
    )

    assert result.unique_entities == 40
    assert result.repeat_entities + result.one_time_entities == result.unique_entities
    assert result.average_value_per_entity is not None


def test_distribution_reports_statistics_and_buckets(sales_frame: pd.DataFrame) -> None:
    from app.schemas.analytics import DistributionRequest

    result = analytics_engine.build_distribution(
        sales_frame, DistributionRequest(column="revenue", bins=5)
    )

    assert result.count == ROWS
    assert len(result.buckets) == 5
    assert result.mean is not None
    assert "p50" in result.percentiles


def test_distribution_rejects_a_text_column(sales_frame: pd.DataFrame) -> None:
    from app.schemas.analytics import DistributionRequest

    with pytest.raises(ValidationError, match="needs a numeric column"):
        analytics_engine.build_distribution(
            sales_frame, DistributionRequest(column="category")
        )


# --- KPI catalogue -----------------------------------------------------------


class _FakeDataset:
    id = uuid.uuid4()


class _FakeLoaded:
    """Minimal stand-in for LoadedDataset; build_catalog only reads ids."""

    dataset = _FakeDataset()
    version_id = None


def catalog_for(frame: pd.DataFrame):
    from app.services.analytics_service import build_catalog

    return build_catalog(frame, _FakeLoaded())  # type: ignore[arg-type]


def suggested(frame: pd.DataFrame) -> set[tuple[str, str | None]]:
    """(metric, column) pairs the catalogue offers."""
    catalog = catalog_for(frame)
    return {
        (
            item.definition.metric.value if item.definition.metric else "formula",
            item.definition.column,
        )
        for item in catalog.suggestions
    }


def test_catalogue_never_suggests_summing_an_identifier(sales_frame: pd.DataFrame) -> None:
    """The reported bug: SUM(order_id) and AVERAGE(customer_id) were offered."""
    offered = suggested(sales_frame)

    assert ("sum", "order_id") not in offered
    assert ("average", "order_id") not in offered
    assert ("sum", "customer_id") not in offered
    assert ("average", "customer_id") not in offered


def test_catalogue_suggests_distinct_counts_for_identifiers(sales_frame: pd.DataFrame) -> None:
    offered = suggested(sales_frame)

    assert ("distinct_count", "order_id") in offered
    assert ("distinct_count", "customer_id") in offered


def test_catalogue_still_suggests_totals_for_real_measures(sales_frame: pd.DataFrame) -> None:
    offered = suggested(sales_frame)

    assert ("sum", "revenue") in offered
    assert ("average", "revenue") in offered
    assert ("sum", "quantity") in offered


def test_catalogue_always_offers_a_row_count(sales_frame: pd.DataFrame) -> None:
    assert ("count", None) in suggested(sales_frame)


def test_catalogue_explains_what_it_cannot_offer() -> None:
    """A dataset of identifiers only has nothing meaningful to total."""
    frame = pd.DataFrame({"order_id": range(1, 51), "note": [f"n{i}" for i in range(50)]})

    catalog = catalog_for(frame)
    reasons = {item["kpi"] for item in catalog.unavailable}

    assert "Value totals and averages" in reasons
    assert "Growth and time-series KPIs" in reasons
    assert all(
        definition.metric is not MetricType.SUM
        for definition in (item.definition for item in catalog.suggestions)
    )
