"""Build the canonical report.

This module answers one question: given a loaded dataset, which sections can
this report contain and what is in them? It produces a :class:`ReportData`,
and every renderer works from that object alone.

Two rules hold the design together:

1. Nothing is computed twice. KPIs, trends, anomalies and quality come from
   the analyst report that was already built; ABC, Pareto, RFM, cohort, churn
   and forecasting come from the existing engines. This module aggregates and
   formats - it contains no new statistics.
2. Nothing is assumed about the schema. Every section declares the business
   roles it needs; a section whose roles are missing is reported as skipped,
   with the reason, rather than rendered empty or filled with invented data.

It is pure and synchronous: no I/O, no database, no AI calls. Any AI narrative
is passed in on the analyst report.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.core.logging import get_logger
from app.models.report import ReportTemplateName
from app.schemas.advanced_analytics import ForecastMethod
from app.schemas.ai_analyst import AnalystReport
from app.schemas.analytics import (
    AbcRequest,
    MetricType,
    SegmentRequest,
    TimePeriod,
    TimeSeriesRequest,
)
from app.schemas.insights import (
    BusinessInsight,
    InsightCategory,
    InsightPriority,
    InsightReport,
)
from app.schemas.profiling import DataQualitySummary, DatasetProfile
from app.schemas.report import (
    ReportCell,
    ReportData,
    ReportMetric,
    ReportSection,
    ReportSectionKey,
    ReportTable,
)
from app.services import advanced_analytics_engine as advanced_engine
from app.services import (
    advanced_analytics_service,
    analytics_engine,
    dataset_access,
    dataset_eda,
    semantic_columns,
)

logger = get_logger(__name__)

Key = ReportSectionKey

#: Rows kept per table. Truncation is decided once, here, so every format
#: shows the same figures and the same "showing top N" note.
TABLE_ROW_LIMIT = 25
#: Cohort matrices are wide; keep them readable in a slide or a page.
COHORT_ROW_LIMIT = 12
#: Correlation pairs worth reporting at all.
MIN_CORRELATION_STRENGTH = 0.3

SECTION_TITLES: dict[ReportSectionKey, str] = {
    Key.EXECUTIVE_SUMMARY: "Executive summary",
    Key.BUSINESS_HEALTH: "Business health",
    Key.CRITICAL_INSIGHTS: "Critical insights",
    Key.OPPORTUNITIES: "Opportunities",
    Key.RISKS: "Risks",
    Key.DATASET_OVERVIEW: "Dataset overview",
    Key.DATA_QUALITY: "Data quality",
    Key.KPIS: "Key performance indicators",
    Key.EDA: "Exploratory analysis",
    Key.TRENDS: "Trends over time",
    Key.SEGMENTATION: "Segmentation (clustering)",
    Key.ABC: "ABC analysis",
    Key.PARETO: "Pareto analysis",
    Key.RFM: "RFM analysis",
    Key.COHORT: "Cohort retention",
    Key.CHURN: "Churn and inactivity",
    Key.CORRELATION: "Correlations",
    Key.OUTLIERS: "Outliers and anomalies",
    Key.FORECAST: "Forecast",
    Key.AI_INSIGHTS: "AI insights",
    Key.RECOMMENDATIONS: "Recommendations",
}

#: Business roles each section needs, using the same vocabulary as
#: ``advanced_analytics_service.REQUIREMENTS``. An empty list means the
#: section works on any dataset.
SECTION_REQUIREMENTS: dict[ReportSectionKey, list[str]] = {
    Key.EXECUTIVE_SUMMARY: [],
    # The insight sections work on any dataset: the engine reports what it
    # could not measure rather than needing a particular column to exist.
    Key.BUSINESS_HEALTH: [],
    Key.CRITICAL_INSIGHTS: [],
    Key.OPPORTUNITIES: [],
    Key.RISKS: [],
    Key.DATASET_OVERVIEW: [],
    Key.DATA_QUALITY: [],
    Key.KPIS: [],
    Key.EDA: [],
    Key.AI_INSIGHTS: [],
    Key.RECOMMENDATIONS: [],
    Key.TRENDS: ["date"],
    Key.SEGMENTATION: ["measure"],
    Key.ABC: ["dimension", "revenue"],
    Key.PARETO: ["dimension", "revenue"],
    Key.RFM: ["customer", "date", "revenue"],
    Key.COHORT: ["customer", "date"],
    Key.CHURN: ["customer", "date"],
    Key.CORRELATION: ["measure"],
    Key.OUTLIERS: ["measure"],
    Key.FORECAST: ["date", "revenue"],
}

#: Canonical order. A report always reads in this sequence, whatever order the
#: sections were requested in.
SECTION_ORDER: list[ReportSectionKey] = [
    Key.EXECUTIVE_SUMMARY,
    Key.BUSINESS_HEALTH,
    Key.CRITICAL_INSIGHTS,
    Key.DATASET_OVERVIEW,
    Key.DATA_QUALITY,
    Key.KPIS,
    Key.EDA,
    Key.TRENDS,
    Key.FORECAST,
    Key.ABC,
    Key.PARETO,
    Key.SEGMENTATION,
    Key.RFM,
    Key.COHORT,
    Key.CHURN,
    Key.CORRELATION,
    Key.OUTLIERS,
    Key.OPPORTUNITIES,
    Key.RISKS,
    Key.AI_INSIGHTS,
    Key.RECOMMENDATIONS,
]

TEMPLATES: dict[ReportTemplateName, dict[str, Any]] = {
    ReportTemplateName.EXECUTIVE: {
        "name": "Executive business review",
        "description": (
            "A short board-level read: headline figures, how they are moving, "
            "data confidence and what to do next."
        ),
        "sections": [
            Key.EXECUTIVE_SUMMARY,
            Key.BUSINESS_HEALTH,
            Key.CRITICAL_INSIGHTS,
            Key.DATASET_OVERVIEW,
            Key.KPIS,
            Key.TRENDS,
            Key.DATA_QUALITY,
            Key.OPPORTUNITIES,
            Key.RISKS,
            Key.AI_INSIGHTS,
            Key.RECOMMENDATIONS,
        ],
    },
    ReportTemplateName.SALES: {
        "name": "Sales analytics",
        "description": (
            "Where the value sits and where it is going: KPIs, trends, "
            "concentration (ABC and Pareto), forecast and anomalies."
        ),
        "sections": [
            Key.EXECUTIVE_SUMMARY,
            Key.KPIS,
            Key.TRENDS,
            Key.FORECAST,
            Key.ABC,
            Key.PARETO,
            Key.OUTLIERS,
            Key.OPPORTUNITIES,
            Key.RISKS,
            Key.AI_INSIGHTS,
            Key.RECOMMENDATIONS,
        ],
    },
    ReportTemplateName.CUSTOMER: {
        "name": "Customer analytics",
        "description": (
            "Who the customers are and whether they stay: RFM, retention "
            "cohorts, inactivity risk and behavioural clusters."
        ),
        "sections": [
            Key.EXECUTIVE_SUMMARY,
            Key.KPIS,
            Key.RFM,
            Key.COHORT,
            Key.CHURN,
            Key.SEGMENTATION,
            Key.BUSINESS_HEALTH,
            Key.RISKS,
            Key.AI_INSIGHTS,
            Key.RECOMMENDATIONS,
        ],
    },
    ReportTemplateName.FULL: {
        "name": "Full BI report",
        "description": "Every section this dataset supports, in reading order.",
        "sections": list(SECTION_ORDER),
    },
}


# --- Formatting --------------------------------------------------------------


def cell_text(value: ReportCell) -> str:
    """Render a cell for the text-based formats.

    Shared by PDF, PPTX and CSV so a number is never formatted two ways.
    """
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return "-"
        if value == int(value) and abs(value) < 1e15:
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _number(value: float | int | None, suffix: str = "") -> str:
    return "Not available" if value is None else f"{cell_text(value)}{suffix}"


def _truncate(
    rows: list[list[ReportCell]], limit: int
) -> tuple[list[list[ReportCell]], str | None]:
    if len(rows) <= limit:
        return rows, None
    return rows[:limit], f"Showing the first {limit:,} of {len(rows):,} rows."


def _table(
    columns: list[str],
    rows: list[list[ReportCell]],
    *,
    title: str | None = None,
    limit: int = TABLE_ROW_LIMIT,
) -> ReportTable:
    kept, note = _truncate(rows, limit)
    return ReportTable(title=title, columns=columns, rows=kept, note=note)


# --- Section availability ----------------------------------------------------


def missing_roles(
    key: ReportSectionKey,
    present: dict[str, str | None],
    model: semantic_columns.SemanticModel,
) -> list[str]:
    """Roles this section needs that the dataset does not offer."""
    missing = [role for role in SECTION_REQUIREMENTS[key] if not present.get(role)]
    # Clustering is the one section that needs more than one of a role.
    if key is Key.SEGMENTATION and not missing and len(model.measures) < 2:
        missing.append("measure")
    if key is Key.CORRELATION and not missing and len(model.measures) < 2:
        missing.append("measure")
    return missing


def unavailable_reason(key: ReportSectionKey, missing: list[str]) -> str:
    if key in (Key.SEGMENTATION, Key.CORRELATION):
        return (
            f"{SECTION_TITLES[key]} needs at least two numeric measures. "
            "This dataset does not have them."
        )
    return advanced_analytics_service.describe_requirement(
        SECTION_TITLES[key], SECTION_REQUIREMENTS[key]
    )


def available_sections(
    model: semantic_columns.SemanticModel,
) -> tuple[list[ReportSectionKey], dict[ReportSectionKey, str]]:
    """Split every known section into supported and unsupported-with-reason."""
    present = advanced_analytics_service.present_roles(model)
    supported: list[ReportSectionKey] = []
    reasons: dict[ReportSectionKey, str] = {}

    for key in SECTION_ORDER:
        missing = missing_roles(key, present, model)
        if missing:
            reasons[key] = unavailable_reason(key, missing)
        else:
            supported.append(key)

    return supported, reasons


def template_sections(template: ReportTemplateName) -> list[ReportSectionKey]:
    sections: list[ReportSectionKey] = TEMPLATES[template]["sections"]
    return list(sections)


# --- Sections ----------------------------------------------------------------


def _executive_summary(frame: pd.DataFrame, analyst: AnalystReport) -> ReportSection:
    narrative = [analyst.summary]
    if analyst.ai and analyst.ai.executive_summary:
        narrative.append(analyst.ai.executive_summary)

    metrics = [
        ReportMetric(label="Rows", value=f"{len(frame):,}"),
        ReportMetric(label="Columns", value=f"{len(frame.columns):,}"),
    ]
    for kpi in [item for item in analyst.kpis if item.available and item.value is not None][:4]:
        metrics.append(
            ReportMetric(label=kpi.name, value=_number(kpi.value), detail=kpi.column)
        )

    bullets = [
        f"{insight.title}: {insight.summary}"
        for insight in analyst.insights
        if insight.severity.value in ("high", "medium")
    ][:6]

    return ReportSection(
        key=Key.EXECUTIVE_SUMMARY,
        title=SECTION_TITLES[Key.EXECUTIVE_SUMMARY],
        narrative=narrative,
        metrics=metrics,
        bullets=bullets,
    )


def _dataset_overview(
    loaded: dataset_access.LoadedDataset,
    profile: DatasetProfile,
    model: semantic_columns.SemanticModel,
) -> ReportSection:
    metrics = [
        ReportMetric(label="Rows", value=f"{profile.row_count:,}"),
        ReportMetric(label="Columns", value=f"{profile.column_count:,}"),
        ReportMetric(
            label="Duplicate rows",
            value=f"{profile.duplicate_row_count:,}",
            detail=f"{profile.duplicate_row_percentage:.2f}% of rows",
        ),
        ReportMetric(
            label="Missing cells",
            value=f"{profile.missing_cell_count:,}",
            detail=f"{profile.missing_cell_percentage:.2f}% of cells",
        ),
    ]

    columns_table = _table(
        ["Column", "Type", "Missing", "Missing %", "Unique"],
        [
            [
                column.column_name,
                column.detected_data_type.value,
                column.null_count,
                round(column.null_percentage, 2),
                column.unique_count,
            ]
            for column in profile.columns
        ],
        title="Columns",
        limit=60,
    )

    roles_table = _table(
        ["Business role", "Column", "Why"],
        [[item.role, item.column, item.reason] for item in model.as_schema()],
        title="Detected business roles",
        limit=30,
    )

    narrative = [
        f"This report covers '{loaded.dataset.name}' "
        f"({'the original upload' if loaded.version is None else 'a cleaned version'}). "
        "Column roles below were detected from column types and names; no role is "
        "assumed to exist."
    ]

    return ReportSection(
        key=Key.DATASET_OVERVIEW,
        title=SECTION_TITLES[Key.DATASET_OVERVIEW],
        narrative=narrative,
        metrics=metrics,
        tables=[columns_table, roles_table],
    )


def _data_quality(quality: DataQualitySummary) -> ReportSection:
    metrics = [
        ReportMetric(label="Quality score", value=f"{quality.score}/100"),
        ReportMetric(label="Status", value=quality.status.value.replace("_", " ")),
        ReportMetric(label="Critical issues", value=f"{quality.critical_count:,}"),
        ReportMetric(label="Warnings", value=f"{quality.warning_count:,}"),
    ]

    issues = _table(
        ["Severity", "Column", "Issue", "Rows affected"],
        [
            [
                issue.severity.value,
                issue.column or "(whole dataset)",
                issue.message,
                issue.affected_rows,
            ]
            for issue in quality.issues
        ],
        title="Issues found",
        limit=30,
    )

    narrative = [
        "Every rule below is a fixed threshold applied to the computed profile, "
        "so the same dataset always produces the same issues and the same score."
    ]
    if not quality.issues:
        narrative.append("No quality issues were detected against these rules.")

    return ReportSection(
        key=Key.DATA_QUALITY,
        title=SECTION_TITLES[Key.DATA_QUALITY],
        narrative=narrative,
        metrics=metrics,
        tables=[issues] if quality.issues else [],
        bullets=quality.rules[:12],
    )


def _kpis(analyst: AnalystReport) -> ReportSection:
    rows: list[list[ReportCell]] = [
        [
            kpi.name,
            kpi.metric,
            kpi.column or "-",
            kpi.value if kpi.available else None,
            "" if kpi.available else (kpi.reason or "Not available"),
        ]
        for kpi in analyst.kpis
    ]
    return ReportSection(
        key=Key.KPIS,
        title=SECTION_TITLES[Key.KPIS],
        narrative=[
            "KPIs are derived from the detected column roles. Anything this "
            "dataset cannot support is listed with the reason instead of a value."
        ],
        metrics=[
            ReportMetric(label=kpi.name, value=_number(kpi.value))
            for kpi in analyst.kpis
            if kpi.available and kpi.value is not None
        ][:6],
        tables=[_table(["KPI", "Metric", "Column", "Value", "Note"], rows, limit=30)],
    )


def _eda(
    frame: pd.DataFrame,
    loaded: dataset_access.LoadedDataset,
) -> ReportSection:
    summary = dataset_eda.build_summary(
        frame, dataset_id=loaded.dataset.id, version_id=loaded.version_id
    )

    tables = []
    if summary.numeric:
        tables.append(
            _table(
                ["Column", "Mean", "Median", "Min", "Max", "Std dev"],
                [
                    [item.column, item.mean, item.median, item.minimum, item.maximum, item.std_dev]
                    for item in summary.numeric
                ],
                title="Numeric columns",
            )
        )
    if summary.categorical:
        tables.append(
            _table(
                ["Column", "Unique values", "Most frequent", "Share"],
                [
                    [
                        item.column,
                        item.unique_count,
                        str(item.top_values[0]["value"]) if item.top_values else "-",
                        (
                            f"{item.top_values[0]['percentage']}%"
                            if item.top_values
                            else "-"
                        ),
                    ]
                    for item in summary.categorical
                ],
                title="Categorical columns",
            )
        )
    if summary.dates:
        tables.append(
            _table(
                ["Column", "Earliest", "Latest", "Span (days)"],
                [
                    [item.column, item.minimum or "-", item.maximum or "-", item.range_days]
                    for item in summary.dates
                ],
                title="Date columns",
            )
        )

    return ReportSection(
        key=Key.EDA,
        title=SECTION_TITLES[Key.EDA],
        narrative=["Descriptive statistics per column, grouped by detected type."],
        tables=tables,
    )


def _trends(analyst: AnalystReport) -> ReportSection:
    rows: list[list[ReportCell]] = [
        [
            trend.metric_column,
            trend.period.value,
            trend.direction.value.replace("_", " "),
            trend.first_label or "-",
            trend.first_value,
            trend.last_label or "-",
            trend.last_value,
            trend.percentage_change,
        ]
        for trend in analyst.trends
    ]

    bullets = []
    for trend in analyst.trends:
        if trend.note:
            bullets.append(f"{trend.metric_column}: {trend.note}")
        elif trend.percentage_change is not None:
            bullets.append(
                f"{trend.metric_column} is {trend.direction.value} - "
                f"{trend.percentage_change:+.1f}% from {trend.first_label} to {trend.last_label} "
                f"(peak {cell_text(trend.highest_value)} in {trend.highest_label})."
            )

    return ReportSection(
        key=Key.TRENDS,
        title=SECTION_TITLES[Key.TRENDS],
        narrative=[
            "Each measure is aggregated on the detected date column. A direction "
            "is only stated when there are enough periods to support it."
        ],
        tables=[
            _table(
                ["Measure", "Period", "Direction", "From", "First", "To", "Last", "Change %"],
                rows,
            )
        ],
        bullets=bullets[:8],
    )


def _abc(frame: pd.DataFrame, dimension: str, revenue: str) -> ReportSection:
    result = analytics_engine.build_abc(
        frame,
        AbcRequest(dimension=dimension, metric=MetricType.SUM, column=revenue),
    )

    summary_rows: list[list[ReportCell]] = [
        [
            item.abc_class,
            item.item_count,
            item.total_value,
            round(item.percentage_of_total, 2),
            round(item.percentage_of_items, 2),
        ]
        for item in result.summary
    ]
    detail_rows: list[list[ReportCell]] = [
        [row.label, row.value, row.percentage, row.cumulative_percentage, row.abc_class]
        for row in result.rows
    ]

    class_a = next((item for item in result.summary if item.abc_class == "A"), None)
    narrative = [
        f"Items in '{dimension}' ranked by total {revenue}, then split at "
        f"{result.a_threshold:.0f}% and {result.b_threshold:.0f}% cumulative contribution."
    ]
    if class_a:
        narrative.append(
            f"Class A is {class_a.item_count:,} item(s) - "
            f"{class_a.percentage_of_items:.1f}% of items carrying "
            f"{class_a.percentage_of_total:.1f}% of the value."
        )

    return ReportSection(
        key=Key.ABC,
        title=SECTION_TITLES[Key.ABC],
        narrative=narrative,
        metrics=[ReportMetric(label=f"Total {revenue}", value=_number(result.total))],
        tables=[
            _table(
                ["Class", "Items", "Value", "% of value", "% of items"],
                summary_rows,
                title="Classes",
            ),
            _table(
                ["Item", "Value", "% of total", "Cumulative %", "Class"],
                detail_rows,
                title="Ranked items",
            ),
        ],
    )


def _pareto(frame: pd.DataFrame, dimension: str, revenue: str) -> ReportSection:
    threshold = 80.0
    contribution = analytics_engine.build_contribution(
        frame,
        SegmentRequest(dimension=dimension, metric=MetricType.SUM, column=revenue, limit=100),
    )
    rows, vital_few = advanced_engine.pareto_from_contribution(contribution, threshold)

    share_of_items = (
        (vital_few / contribution.group_count) * 100 if contribution.group_count else 0.0
    )

    return ReportSection(
        key=Key.PARETO,
        title=SECTION_TITLES[Key.PARETO],
        narrative=[
            f"The smallest set of '{dimension}' values that together account for "
            f"{threshold:.0f}% of total {revenue}."
        ],
        metrics=[
            ReportMetric(label="Vital few", value=f"{vital_few:,} items"),
            ReportMetric(
                label="Share of all items",
                value=f"{share_of_items:.1f}%",
                detail=f"of {contribution.group_count:,} groups",
            ),
            ReportMetric(label=f"Total {revenue}", value=_number(contribution.total)),
        ],
        tables=[
            _table(
                ["Item", "Value", "% of total", "Cumulative %", "Vital few"],
                [
                    [
                        row.label,
                        row.value,
                        row.percentage,
                        row.cumulative_percentage,
                        row.within_threshold,
                    ]
                    for row in rows
                ],
            )
        ],
    )


def _rfm(frame: pd.DataFrame, customer: str, date: str, monetary: str) -> ReportSection:
    segments, customers, context = advanced_engine.build_rfm(frame, customer, date, monetary)

    return ReportSection(
        key=Key.RFM,
        title=SECTION_TITLES[Key.RFM],
        narrative=[
            f"Customers in '{customer}' scored 1-5 on recency (from '{date}'), "
            f"frequency and monetary value (from '{monetary}'), relative to "
            f"{context['reference_date']}."
        ],
        metrics=[
            ReportMetric(label="Customers", value=f"{int(context['customer_count']):,}"),
            ReportMetric(label=f"Total {monetary}", value=_number(context["total_monetary"])),
        ],
        tables=[
            _table(
                ["Segment", "Customers", "% of customers", "Value", "% of value", "Avg recency"],
                [
                    [
                        item.segment.value.replace("_", " "),
                        item.customer_count,
                        item.percentage,
                        item.total_monetary,
                        item.monetary_percentage,
                        round(item.average_recency_days, 1),
                    ]
                    for item in segments
                ],
                title="Segments",
            ),
            _table(
                ["Customer", "Recency (days)", "Frequency", "Monetary", "RFM", "Segment"],
                [
                    [
                        item.customer,
                        item.recency_days,
                        item.frequency,
                        item.monetary,
                        item.rfm_score,
                        item.segment.value.replace("_", " "),
                    ]
                    for item in customers
                ],
                title="Top customers",
            ),
        ],
    )


def _cohort(frame: pd.DataFrame, customer: str, date: str) -> ReportSection:
    rows, labels, averages = advanced_engine.build_cohort(
        frame, customer, date, TimePeriod.MONTH, 12
    )

    matrix: list[list[ReportCell]] = [
        [row.cohort, row.cohort_size, *row.percentages] for row in rows
    ]

    return ReportSection(
        key=Key.COHORT,
        title=SECTION_TITLES[Key.COHORT],
        narrative=[
            f"Customers from '{customer}' grouped by the month of their first "
            f"activity in '{date}'. Each cell is the share of that cohort still "
            "active in the given month."
        ],
        metrics=[
            ReportMetric(
                label="Month 1 retention",
                value=(
                    f"{averages[1]:.1f}%" if len(averages) > 1 and averages[1] is not None else "-"
                ),
                detail="average across cohorts",
            ),
            ReportMetric(label="Cohorts", value=f"{len(rows):,}"),
        ],
        tables=[
            _table(
                ["Cohort", "Size", *labels],
                matrix,
                title="Retention %",
                limit=COHORT_ROW_LIMIT,
            )
        ],
    )


def _churn(
    frame: pd.DataFrame, customer: str, date: str, monetary: str | None
) -> ReportSection:
    result = advanced_engine.build_churn(frame, customer, date, monetary, 90, 45, 20)

    metrics = [
        ReportMetric(label="Customers", value=f"{result['total_customers']:,}"),
        ReportMetric(label="Active", value=f"{result['active_customers']:,}"),
        ReportMetric(label="At risk", value=f"{result['at_risk_customers']:,}"),
        ReportMetric(label="Churned", value=f"{result['churned_customers']:,}"),
        ReportMetric(label="Churn rate", value=f"{result['churn_rate']:.1f}%"),
    ]
    if result.get("revenue_at_risk") is not None:
        metrics.append(
            ReportMetric(label="Value at risk", value=_number(result["revenue_at_risk"]))
        )

    return ReportSection(
        key=Key.CHURN,
        title=SECTION_TITLES[Key.CHURN],
        narrative=[
            "Rule-based classification: customers are grouped by days since their "
            "last recorded activity (churned after 90 days, at risk after 45). "
            "No predictive model is trained and nothing is forecast."
        ],
        metrics=metrics,
        tables=[
            _table(
                ["Customer", "Last activity", "Days inactive", "Transactions", "Value", "Status"],
                [
                    [
                        item.customer,
                        item.last_activity,
                        item.days_since_activity,
                        item.transactions,
                        item.monetary,
                        item.status.value.replace("_", " "),
                    ]
                    for item in result["customers"]
                ],
                title="Customers needing attention",
            )
        ],
    )


def _segmentation(frame: pd.DataFrame, model: semantic_columns.SemanticModel) -> ReportSection:
    features = [column.name for column in model.measures][:5]
    profiles, _points, context = advanced_engine.build_segmentation(
        frame, features, 4, True, None, 1
    )

    columns = ["Cluster", "Size", "% of rows", *context["features"]]
    rows: list[list[ReportCell]] = [
        [
            f"Cluster {profile.cluster}",
            profile.size,
            profile.percentage,
            *[profile.averages.get(feature) for feature in context["features"]],
        ]
        for profile in profiles
    ]

    narrative = [
        "K-Means clustering on "
        + ", ".join(f"'{feature}'" for feature in context["features"])
        + ". The algorithm is seeded, so the same data always yields the same clusters."
    ]
    variance = context.get("explained_variance")
    if variance is not None:
        narrative.append(
            f"The two leading components capture {variance * 100:.0f}% of the "
            "variance across those features."
        )

    return ReportSection(
        key=Key.SEGMENTATION,
        title=SECTION_TITLES[Key.SEGMENTATION],
        narrative=narrative,
        metrics=[ReportMetric(label="Clusters", value=str(len(profiles)))],
        tables=[_table(columns, rows, title="Cluster profiles")],
    )


def _correlation(frame: pd.DataFrame, loaded: dataset_access.LoadedDataset) -> ReportSection:
    result = dataset_eda.build_correlation(
        frame, dataset_id=loaded.dataset.id, version_id=loaded.version_id
    )

    if result.message:
        return ReportSection(
            key=Key.CORRELATION,
            title=SECTION_TITLES[Key.CORRELATION],
            unavailable_reason=result.message,
        )

    pairs: list[tuple[float, str, str]] = []
    for row_index, row_name in enumerate(result.columns):
        for column_index in range(row_index + 1, len(result.columns)):
            value = result.matrix[row_index][column_index]
            if value is None:
                continue
            pairs.append((value, row_name, result.columns[column_index]))

    strong = sorted(pairs, key=lambda item: abs(item[0]), reverse=True)
    reportable = [item for item in strong if abs(item[0]) >= MIN_CORRELATION_STRENGTH]

    def label(value: float) -> str:
        strength = "strong" if abs(value) >= 0.7 else "moderate" if abs(value) >= 0.5 else "weak"
        return f"{strength} {'positive' if value > 0 else 'negative'}"

    narrative = [
        "Pearson correlation across numeric columns. These are associations "
        "between columns, not evidence that one causes the other."
    ]
    if not reportable:
        narrative.append(
            f"No pair reached a correlation of {MIN_CORRELATION_STRENGTH:.1f}; "
            "the strongest pairs are listed anyway."
        )

    return ReportSection(
        key=Key.CORRELATION,
        title=SECTION_TITLES[Key.CORRELATION],
        narrative=narrative,
        tables=[
            _table(
                ["Column A", "Column B", "Correlation", "Reading"],
                [
                    [first, second, round(value, 3), label(value)]
                    for value, first, second in (reportable or strong)
                ],
                title="Strongest pairs",
                limit=15,
            )
        ],
    )


def _outliers(analyst: AnalystReport) -> ReportSection:
    rows: list[list[ReportCell]] = [
        [
            anomaly.metric_column,
            anomaly.method,
            anomaly.outlier_count,
            anomaly.outlier_percentage,
            anomaly.lower_bound,
            anomaly.upper_bound,
            anomaly.minimum_outlier,
            anomaly.maximum_outlier,
        ]
        for anomaly in analyst.anomalies
    ]

    bullets = []
    for anomaly in analyst.anomalies:
        periods = anomaly.context.get("unusual_periods") or []
        for period in periods[:2]:
            bullets.append(
                f"{anomaly.metric_column}: {period.get('label')} is unusual at "
                f"{cell_text(period.get('value'))}."
            )

    return ReportSection(
        key=Key.OUTLIERS,
        title=SECTION_TITLES[Key.OUTLIERS],
        narrative=[
            "Values outside the expected range for their column. These are "
            "candidates for review, not confirmed errors - nothing is removed."
        ],
        tables=[
            _table(
                ["Column", "Method", "Outliers", "% of values", "Lower", "Upper", "Min", "Max"],
                rows,
            )
        ],
        bullets=bullets[:6],
    )


def _forecast(frame: pd.DataFrame, date: str, revenue: str) -> ReportSection:
    series = analytics_engine.build_time_series(
        frame,
        TimeSeriesRequest(
            date_column=date,
            period=TimePeriod.MONTH,
            metric=MetricType.SUM,
            column=revenue,
            max_points=500,
        ),
    )
    points = [
        point
        for point in (series.series[0].points if series.series else [])
        if point.value is not None
    ]
    history, projection, context = advanced_engine.build_forecast(
        [point.label for point in points],
        [float(point.value or 0) for point in points],
        ForecastMethod.HOLT,
        6,
        TimePeriod.MONTH,
    )

    rows: list[list[ReportCell]] = [
        [point.period, point.value, point.lower_bound, point.upper_bound]
        for point in projection
    ]

    return ReportSection(
        key=Key.FORECAST,
        title=SECTION_TITLES[Key.FORECAST],
        narrative=[
            f"Monthly {revenue} projected six periods ahead with Holt's linear "
            "exponential smoothing. Intervals come from the model's own residuals; "
            "they widen with distance and are not a guarantee.",
        ],
        metrics=[
            ReportMetric(label="Periods observed", value=f"{context['periods_observed']:,}"),
            ReportMetric(label="Trend", value=str(context["trend"])),
            ReportMetric(
                label="Mean absolute error",
                value=_number(context.get("mean_absolute_error")),
                detail="on the observed history",
            ),
        ],
        tables=[
            _table(["Period", "Forecast", "Lower bound", "Upper bound"], rows, title="Projection"),
            _table(
                ["Period", "Actual"],
                [[point.period, point.value] for point in history[-12:]],
                title="Recent history",
            ),
        ],
    )


def _ai_insights(analyst: AnalystReport) -> ReportSection:
    if analyst.ai is None:
        return ReportSection(
            key=Key.AI_INSIGHTS,
            title=SECTION_TITLES[Key.AI_INSIGHTS],
            unavailable_reason=(
                analyst.ai_status
                or "No AI provider is configured, so this report is deterministic only."
            ),
        )

    narrative = []
    if analyst.ai.executive_summary:
        narrative.append(analyst.ai.executive_summary)
    if analyst.ai.contains_untraceable_numbers:
        narrative.append(
            "Note: this narrative contains figures that could not be traced back "
            "to the computed statistics. Treat them with caution and rely on the "
            "tables above."
        )

    return ReportSection(
        key=Key.AI_INSIGHTS,
        title=SECTION_TITLES[Key.AI_INSIGHTS],
        narrative=narrative,
        bullets=list(analyst.ai.key_findings),
        metrics=[
            ReportMetric(
                label="Generated by",
                value=f"{analyst.ai.provider or 'unknown'} / {analyst.ai.model or 'unknown'}",
            )
        ],
    )


def _recommendations(
    analyst: AnalystReport, insights: InsightReport | None
) -> ReportSection:
    bullets = list(analyst.recommendations)
    if analyst.ai:
        for item in analyst.ai.recommendations:
            if item not in bullets:
                bullets.append(item)

    tables = []
    if insights and insights.recommendations:
        # The insight engine produces a ranked plan with reasons and impact;
        # that is richer than a bullet, so it gets a table of its own.
        tables.append(
            _table(
                ["Priority", "Action", "Why", "Potential impact"],
                [
                    [
                        item.priority.value,
                        item.action,
                        item.reason,
                        item.expected_impact,
                    ]
                    for item in insights.recommendations
                ],
                title="Prioritised actions",
            )
        )

    return ReportSection(
        key=Key.RECOMMENDATIONS,
        title=SECTION_TITLES[Key.RECOMMENDATIONS],
        narrative=[
            "Each recommendation is tied to a finding in this report. Nothing "
            "here is generic advice, and no financial outcome is guaranteed."
        ],
        bullets=bullets[:12],
        tables=tables,
        unavailable_reason=(
            None
            if bullets or tables
            else "No finding in this report warranted a recommendation."
        ),
    )


# --- Insight-backed sections -------------------------------------------------
#
# These reuse the AI Insights engine rather than adding a second reporting
# path: the report and the Insights page render the same InsightReport, so a
# figure can never differ between the two.


INSIGHT_SECTION_UNAVAILABLE = (
    "This section is produced by the AI Insights engine, which could not be run "
    "for this dataset."
)


def _insight_rows(insights: list[BusinessInsight]) -> list[list[ReportCell]]:
    return [
        [
            insight.title,
            insight.category.value.replace("_", " "),
            insight.severity.value,
            insight.priority.value,
            insight.metric_value,
            insight.percentage_change,
            insight.dimension_value or insight.dimension or "-",
        ]
        for insight in insights
    ]


_INSIGHT_COLUMNS = [
    "Finding",
    "Category",
    "Severity",
    "Priority",
    "Value",
    "Change %",
    "Where",
]


def _business_health(insights: InsightReport) -> ReportSection:
    health = insights.health
    if health.score is None:
        return ReportSection(
            key=Key.BUSINESS_HEALTH,
            title=SECTION_TITLES[Key.BUSINESS_HEALTH],
            unavailable_reason=(
                "No health signal in this dataset could be measured, so no score is "
                "shown rather than an invented one."
            ),
            bullets=[f"{item['factor']}: {item['reason']}" for item in health.excluded],
        )

    return ReportSection(
        key=Key.BUSINESS_HEALTH,
        title=SECTION_TITLES[Key.BUSINESS_HEALTH],
        narrative=[health.methodology],
        metrics=[
            ReportMetric(label="Business health", value=f"{health.score}/100"),
            ReportMetric(
                label="Rating", value=health.rating.value.replace("_", " ").title()
            ),
            ReportMetric(label="Signals measured", value=str(len(health.factors))),
        ],
        tables=[
            _table(
                ["Signal", "Status", "Score", "Weight", "Why"],
                [
                    [
                        factor.name,
                        factor.status.value.replace("_", " "),
                        factor.score,
                        round(factor.weight * 100, 1),
                        factor.detail,
                    ]
                    for factor in health.factors
                ],
                title="Contributing signals",
            )
        ],
        bullets=[
            f"Not measured - {item['factor']}: {item['reason']}"
            for item in health.excluded
        ],
    )


def _critical_insights(insights: InsightReport) -> ReportSection:
    urgent = [
        insight
        for insight in insights.insights
        if insight.priority in (InsightPriority.CRITICAL, InsightPriority.HIGH)
    ]
    if not urgent:
        return ReportSection(
            key=Key.CRITICAL_INSIGHTS,
            title=SECTION_TITLES[Key.CRITICAL_INSIGHTS],
            unavailable_reason=(
                "No finding reached critical or high priority for this dataset."
            ),
        )

    return ReportSection(
        key=Key.CRITICAL_INSIGHTS,
        title=SECTION_TITLES[Key.CRITICAL_INSIGHTS],
        narrative=[
            insights.summary,
            "Priority combines severity, magnitude, how much of the data a finding "
            "covers and how many periods it persists for.",
        ],
        tables=[_table(_INSIGHT_COLUMNS, _insight_rows(urgent), title="Needs attention first")],
        bullets=[f"{item.title}: {item.summary}" for item in urgent[:6]],
    )


def _what_why_action(insights: list[BusinessInsight]) -> ReportTable:
    """The WHAT / WHY / EVIDENCE / ACTION shape, as one readable table."""
    return _table(
        ["What", "Why it matters", "Evidence", "Suggested action"],
        [
            [
                insight.title,
                insight.why or insight.summary,
                "; ".join(
                    f"{item.label}: {item.formatted}" for item in insight.evidence[:4]
                )
                or "-",
                insight.action or "-",
            ]
            for insight in insights
        ],
    )


def _opportunities(insights: InsightReport) -> ReportSection:
    found = [
        item
        for item in insights.insights
        if item.category is InsightCategory.OPPORTUNITY
    ]
    if not found:
        return ReportSection(
            key=Key.OPPORTUNITIES,
            title=SECTION_TITLES[Key.OPPORTUNITIES],
            unavailable_reason=(
                "No opportunity crossed the detection thresholds for this dataset."
            ),
        )
    return ReportSection(
        key=Key.OPPORTUNITIES,
        title=SECTION_TITLES[Key.OPPORTUNITIES],
        narrative=[
            "Areas already performing well where the data suggests there may be room "
            "to do more. Each is stated with the evidence behind it."
        ],
        tables=[_what_why_action(found)],
    )


def _risks(insights: InsightReport) -> ReportSection:
    found = [item for item in insights.insights if item.category is InsightCategory.RISK]
    if not found:
        return ReportSection(
            key=Key.RISKS,
            title=SECTION_TITLES[Key.RISKS],
            unavailable_reason="No risk crossed the detection thresholds for this dataset.",
        )
    return ReportSection(
        key=Key.RISKS,
        title=SECTION_TITLES[Key.RISKS],
        narrative=[
            "Potential risks detected in the data. These describe what the figures "
            "show, not a proven cause - each one is a prompt to investigate rather "
            "than a conclusion."
        ],
        tables=[_what_why_action(found)],
    )


#: Section key -> builder, for the sections fed by the insight engine.
INSIGHT_SECTIONS: dict[ReportSectionKey, Callable[[InsightReport], ReportSection]] = {
    Key.BUSINESS_HEALTH: _business_health,
    Key.CRITICAL_INSIGHTS: _critical_insights,
    Key.OPPORTUNITIES: _opportunities,
    Key.RISKS: _risks,
}


# --- Assembly ----------------------------------------------------------------


def _build_section(
    key: ReportSectionKey,
    frame: pd.DataFrame,
    loaded: dataset_access.LoadedDataset,
    analyst: AnalystReport,
    profile: DatasetProfile,
    quality: DataQualitySummary,
    model: semantic_columns.SemanticModel,
    present: dict[str, str | None],
    insights: InsightReport | None,
) -> ReportSection:
    """Dispatch to the one builder for this section."""
    if key in INSIGHT_SECTIONS:
        if insights is None:
            return ReportSection(
                key=key,
                title=SECTION_TITLES[key],
                unavailable_reason=INSIGHT_SECTION_UNAVAILABLE,
            )
        return INSIGHT_SECTIONS[key](insights)

    customer = present["customer"]
    date = present["date"]
    revenue = present["revenue"]
    dimension = present["dimension"]

    if key is Key.EXECUTIVE_SUMMARY:
        return _executive_summary(frame, analyst)
    if key is Key.DATASET_OVERVIEW:
        return _dataset_overview(loaded, profile, model)
    if key is Key.DATA_QUALITY:
        return _data_quality(quality)
    if key is Key.KPIS:
        return _kpis(analyst)
    if key is Key.EDA:
        return _eda(frame, loaded)
    if key is Key.TRENDS:
        return _trends(analyst)
    if key is Key.ABC:
        return _abc(frame, str(dimension), str(revenue))
    if key is Key.PARETO:
        return _pareto(frame, str(dimension), str(revenue))
    if key is Key.RFM:
        return _rfm(frame, str(customer), str(date), str(revenue))
    if key is Key.COHORT:
        return _cohort(frame, str(customer), str(date))
    if key is Key.CHURN:
        return _churn(frame, str(customer), str(date), revenue)
    if key is Key.SEGMENTATION:
        return _segmentation(frame, model)
    if key is Key.CORRELATION:
        return _correlation(frame, loaded)
    if key is Key.OUTLIERS:
        return _outliers(analyst)
    if key is Key.FORECAST:
        return _forecast(frame, str(date), str(revenue))
    if key is Key.AI_INSIGHTS:
        return _ai_insights(analyst)
    return _recommendations(analyst, insights)


def resolve_sections(
    template: ReportTemplateName,
    requested: list[ReportSectionKey] | None,
) -> list[ReportSectionKey]:
    """The sections to attempt, de-duplicated and in canonical reading order."""
    chosen = set(requested) if requested else set(template_sections(template))
    return [key for key in SECTION_ORDER if key in chosen]


def build(
    frame: pd.DataFrame,
    loaded: dataset_access.LoadedDataset,
    analyst: AnalystReport,
    profile: DatasetProfile,
    quality: DataQualitySummary,
    *,
    project_id: uuid.UUID,
    template: ReportTemplateName,
    sections: list[ReportSectionKey] | None = None,
    title: str | None = None,
    generated_by: str,
    insights: InsightReport | None = None,
) -> ReportData:
    """Assemble the canonical report. Pure: no I/O and no AI calls.

    ``insights`` is the already-computed AI Insights report. It is only needed
    when an insight-backed section was requested, so the caller builds it
    lazily rather than paying for RFM and churn on every export.
    """
    model = semantic_columns.detect(frame)
    present = advanced_analytics_service.present_roles(model)

    built: list[ReportSection] = []
    skipped: list[dict[str, str]] = []

    for key in resolve_sections(template, sections):
        missing = missing_roles(key, present, model)
        if missing:
            skipped.append({"section": key.value, "reason": unavailable_reason(key, missing)})
            continue

        try:
            section = _build_section(
                key, frame, loaded, analyst, profile, quality, model, present, insights
            )
        except Exception:
            # One degenerate section must not cost the user the whole report.
            logger.exception("Report section %s could not be built", key.value)
            skipped.append(
                {
                    "section": key.value,
                    "reason": (
                        f"{SECTION_TITLES[key]} could not be produced from this "
                        "dataset's values."
                    ),
                }
            )
            continue

        if section.unavailable_reason and section.is_empty:
            skipped.append({"section": key.value, "reason": section.unavailable_reason})
            continue

        built.append(section)

    version_label = (
        f"v{loaded.version.version_number} - {loaded.version.name}"
        if loaded.version
        else "Original dataset"
    )

    return ReportData(
        title=title or f"{loaded.dataset.name} - {TEMPLATES[template]['name']}",
        subtitle=TEMPLATES[template]["description"],
        project_id=project_id,
        dataset_id=loaded.dataset.id,
        dataset_name=loaded.dataset.name,
        version_id=loaded.version_id,
        version_label=version_label,
        template=template,
        generated_at=datetime.now(UTC),
        generated_by=generated_by,
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
        sections=built,
        ai_available=analyst.ai_available,
        ai_status=analyst.ai_status,
        skipped=skipped,
    )
