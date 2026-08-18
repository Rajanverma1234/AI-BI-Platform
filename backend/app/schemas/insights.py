"""Business insight schemas.

These sit one level above ``app.schemas.ai_analyst``. The analyst layer answers
"what does this dataset contain?"; this layer answers "what should the business
owner know, and what should they do next?".

The distinction matters for the model: every insight here carries the evidence
it was derived from, a priority whose score is reconstructible, and hedged
wording for anything that is a correlation rather than a cause. Nothing is
fabricated - a field that cannot be measured is left null rather than filled
with a plausible-looking number.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, Page


class InsightCategory(enum.StrEnum):
    """What kind of finding this is, in business terms."""

    PERFORMANCE = "performance"
    OPPORTUNITY = "opportunity"
    RISK = "risk"
    TREND = "trend"
    CUSTOMER = "customer"
    PRODUCT = "product"
    REGION = "region"
    OPERATIONS = "operations"
    DATA_QUALITY = "data_quality"


class InsightSeverity(enum.StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class InsightPriority(enum.StrEnum):
    """How urgently a finding deserves attention.

    ``CRITICAL`` exists so "immediate attention" is expressible as a priority
    and not only as a severity - a low-severity finding affecting most of the
    dataset can still be the most urgent thing on the page.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HealthRating(enum.StrEnum):
    STRONG = "strong"
    HEALTHY = "healthy"
    MIXED = "mixed"
    AT_RISK = "at_risk"
    #: Nothing measurable was found; no score is shown rather than a made-up one.
    UNKNOWN = "unknown"


class FactorStatus(enum.StrEnum):
    POSITIVE = "positive"
    MODERATE = "moderate"
    NEGATIVE = "negative"
    NOT_MEASURABLE = "not_measurable"


class RunStatus(enum.StrEnum):
    READY = "ready"
    FAILED = "failed"


class Evidence(BaseModel):
    """One measured figure behind a finding.

    ``formatted`` is the display string and ``value`` the raw number, so the UI
    can show the figure and a client can still compute with it.
    """

    label: str
    value: float | None = None
    formatted: str
    detail: str | None = None


class BusinessInsight(BaseModel):
    """A single finding, with the evidence that produced it."""

    id: str
    category: InsightCategory
    title: str
    summary: str
    severity: InsightSeverity = InsightSeverity.INFO
    priority: InsightPriority = InsightPriority.LOW

    metric: str | None = None
    metric_value: float | None = None
    comparison_value: float | None = None
    percentage_change: float | None = None
    dimension: str | None = None
    dimension_value: str | None = None

    #: Why this matters to the business. Present on opportunities and risks.
    why: str | None = None
    #: What the business could consider doing about it.
    action: str | None = None
    #: The figures behind the statement - the "why am I seeing this?" panel.
    evidence: list[Evidence] = Field(default_factory=list)
    #: Only set when it means something measurable (a share of rows, a
    #: correlation strength). Never an invented score.
    confidence: float | None = Field(default=None, ge=0, le=1)
    #: Rows or entities the finding covers, when that is knowable.
    affected_records: int | None = None
    recommendation: str | None = None

    #: Which analysis produced this, so a user can go and check it.
    source: str
    #: The prioritisation inputs, kept so the ranking can be explained.
    priority_score: float = 0.0
    priority_reason: str | None = None

    created_at: datetime


class Recommendation(BaseModel):
    """An action derived from one or more insights."""

    id: str
    title: str
    action: str
    reason: str
    #: Ids of the insights that justify this. Never empty for a deterministic
    #: recommendation - an action with no evidence is not offered.
    supporting_insight_ids: list[str] = Field(default_factory=list)
    #: Always phrased as a possibility. No outcome is guaranteed.
    expected_impact: str
    priority: InsightPriority = InsightPriority.MEDIUM
    category: InsightCategory = InsightCategory.PERFORMANCE
    #: "deterministic" or the AI provider name.
    source: str = "deterministic"


class HealthFactor(BaseModel):
    """One measurable signal feeding the business health score."""

    key: str
    name: str
    status: FactorStatus
    #: 0-100 contribution. Null when the factor could not be measured.
    score: float | None = None
    #: Share of the final score this factor carries, after renormalisation.
    weight: float = 0.0
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)


class BusinessHealth(BaseModel):
    """Overall health, with every input shown.

    The score is a weighted mean of the factors that could actually be
    measured; weights are renormalised over those, and anything unmeasurable is
    listed in ``excluded`` with a reason rather than being scored as zero.
    """

    score: int | None = Field(default=None, ge=0, le=100)
    rating: HealthRating = HealthRating.UNKNOWN
    #: Plain-language description of exactly how the score was produced.
    methodology: str
    factors: list[HealthFactor] = Field(default_factory=list)
    excluded: list[dict[str, str]] = Field(default_factory=list)


class InsightFilters(BaseModel):
    """Filter values taken from this dataset, never hard-coded."""

    categories: list[InsightCategory] = Field(default_factory=list)
    severities: list[InsightSeverity] = Field(default_factory=list)
    priorities: list[InsightPriority] = Field(default_factory=list)
    #: Distinct values of the detected product/category dimension.
    products: list[str] = Field(default_factory=list)
    #: Distinct values of the detected region dimension.
    regions: list[str] = Field(default_factory=list)
    #: Customer segments that actually occur (RFM), when customers exist.
    customer_segments: list[str] = Field(default_factory=list)
    #: Period labels from the dataset's own time axis.
    periods: list[str] = Field(default_factory=list)
    #: Which dimension column each list came from, for the UI label.
    product_column: str | None = None
    region_column: str | None = None
    date_column: str | None = None


class AiInsightNarrative(BaseModel):
    """The optional LLM interpretation layer."""

    headline: str | None = None
    interpretation: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    #: True when a figure in the narrative could not be traced to the context.
    contains_untraceable_numbers: bool = False
    untraceable_values: list[str] = Field(default_factory=list)


class InsightReport(BaseModel):
    """The full result of one insight run."""

    run_id: uuid.UUID | None = None
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    version_id: uuid.UUID | None = None
    version_label: str
    #: Bumped when the detection pipeline changes, so a stored run is never
    #: presented as current after the rules that produced it have moved on.
    analysis_version: str
    generated_at: datetime
    generated_by: str
    row_count: int
    column_count: int

    #: Deterministic answer to "what should the business owner know?".
    summary: str
    health: BusinessHealth
    insights: list[BusinessInsight] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    #: Headline figures the insights were drawn from.
    supporting_metrics: list[Evidence] = Field(default_factory=list)
    filters: InsightFilters = Field(default_factory=InsightFilters)

    counts_by_category: dict[str, int] = Field(default_factory=dict)
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
    counts_by_priority: dict[str, int] = Field(default_factory=dict)

    ai_available: bool = False
    #: Why the AI layer was skipped or failed, when it was.
    ai_status: str | None = None
    ai: AiInsightNarrative | None = None
    #: Analyses that could not run, and why - so silence is never mistaken for
    #: "nothing to report".
    skipped: list[dict[str, str]] = Field(default_factory=list)
    #: True when the run is stored against a version that is no longer the one
    #: being viewed, or was produced by an older analysis version.
    stale: bool = False


# --- Requests ----------------------------------------------------------------


class GenerateInsightsRequest(BaseModel):
    version_id: uuid.UUID | None = None
    #: Ask the configured AI provider to interpret the evidence. Deterministic
    #: insights are produced either way.
    include_ai: bool = True
    #: Store the run so it appears in history.
    persist: bool = True


class RefreshInsightsRequest(BaseModel):
    include_ai: bool = True


# --- Responses ---------------------------------------------------------------


class InsightRunResponse(ORMModel):
    """History row. The full result is fetched separately."""

    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID | None = None
    analysis_version: str
    status: RunStatus
    health_score: int | None = None
    health_rating: str | None = None
    insight_count: int
    recommendation_count: int
    ai_available: bool
    ai_status: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


#: Paginated envelope returned by GET .../insights.
InsightRunListResponse = Page[InsightRunResponse]


class InsightRunDetail(BaseModel):
    """A stored run, with its full report."""

    run: InsightRunResponse
    report: InsightReport | None = None


def build_context_payload(report: InsightReport) -> dict[str, Any]:
    """The compact analytical context handed to the AI. Never raw rows."""
    return {
        "dataset": {
            "name": report.dataset_name,
            "rows": report.row_count,
            "columns": report.column_count,
            "version": report.version_label,
        },
        "business_health": {
            "score": report.health.score,
            "rating": report.health.rating.value,
            "factors": [
                {
                    "name": factor.name,
                    "status": factor.status.value,
                    "score": factor.score,
                    "detail": factor.detail,
                }
                for factor in report.health.factors
            ],
        },
        "insights": [
            {
                "id": insight.id,
                "category": insight.category.value,
                "severity": insight.severity.value,
                "priority": insight.priority.value,
                "title": insight.title,
                "summary": insight.summary,
                "metric": insight.metric,
                "metric_value": insight.metric_value,
                "comparison_value": insight.comparison_value,
                "percentage_change": insight.percentage_change,
                "dimension": insight.dimension,
                "dimension_value": insight.dimension_value,
                "evidence": [
                    {"label": item.label, "value": item.value, "formatted": item.formatted}
                    for item in insight.evidence
                ],
            }
            for insight in report.insights
        ],
        "recommendations": [
            {"title": item.title, "action": item.action, "reason": item.reason}
            for item in report.recommendations
        ],
        "supporting_metrics": [
            {"label": item.label, "value": item.value, "formatted": item.formatted}
            for item in report.supporting_metrics
        ],
    }
