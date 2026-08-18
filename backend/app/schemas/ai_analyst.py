"""AI analyst schemas.

The report is structured data, not a blob of prose: deterministic facts are
computed first and the optional AI layer only interprets them. Everything the
AI says is carried alongside the figures it was given, so a number in the
narrative can always be traced back to a computed insight.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.analytics import TimePeriod


class InsightCategory(enum.StrEnum):
    KPI = "kpi"
    TREND = "trend"
    ANOMALY = "anomaly"
    SEGMENT = "segment"
    CUSTOMER = "customer"
    PRODUCT = "product"
    REGION = "region"
    DATA_QUALITY = "data_quality"


class InsightSeverity(enum.StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TrendDirection(enum.StrEnum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    #: Too few observations to call a direction honestly.
    INSUFFICIENT_DATA = "insufficient_data"


class Insight(BaseModel):
    """One deterministic finding.

    `confidence` is only set when it means something measurable (for example
    the share of rows behind a segment). It is never an invented score.
    """

    id: str
    category: InsightCategory
    title: str
    summary: str
    metric: str | None = None
    value: float | None = None
    comparison_value: float | None = None
    percentage_change: float | None = None
    dimension: str | None = None
    dimension_value: str | None = None
    severity: InsightSeverity = InsightSeverity.INFO
    confidence: float | None = Field(default=None, ge=0, le=1)
    #: The figures behind the statement, so the UI (and the AI) can show them.
    supporting_data: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None


class TrendFinding(BaseModel):
    metric_column: str
    date_column: str
    period: TimePeriod
    direction: TrendDirection
    first_label: str | None = None
    last_label: str | None = None
    first_value: float | None = None
    last_value: float | None = None
    percentage_change: float | None = None
    highest_label: str | None = None
    highest_value: float | None = None
    lowest_label: str | None = None
    lowest_value: float | None = None
    periods_observed: int = 0
    #: Set when the series is too short to state a direction.
    note: str | None = None


class AnomalyFinding(BaseModel):
    metric_column: str
    method: str
    #: Rows flagged as outlying by the chosen method.
    outlier_count: int
    outlier_percentage: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    minimum_outlier: float | None = None
    maximum_outlier: float | None = None
    #: Periods or segments whose aggregate value is itself an outlier.
    context: dict[str, Any] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list)


class SegmentFinding(BaseModel):
    dimension: str
    metric_column: str | None = None
    metric: str
    total: float | None = None
    top: list[dict[str, Any]] = Field(default_factory=list)
    bottom: list[dict[str, Any]] = Field(default_factory=list)
    #: Share of the metric held by the largest group.
    top_share_percentage: float | None = None
    #: Number of groups making up 80% of the metric (ABC class A).
    class_a_count: int | None = None
    concentration_note: str | None = None


class DataQualityNote(BaseModel):
    issue_type: str
    severity: str
    column: str | None = None
    message: str
    affected_rows: int = 0


class SemanticColumn(BaseModel):
    """A column mapped to a business role by deterministic name/type rules."""

    role: str
    column: str
    reason: str


class AnalystKpi(BaseModel):
    name: str
    metric: str
    column: str | None = None
    value: float | None = None
    available: bool = True
    reason: str | None = None


class AiNarrative(BaseModel):
    """The optional LLM interpretation layer."""

    executive_summary: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    #: False when every number in the narrative was traceable to the context.
    contains_untraceable_numbers: bool = False
    untraceable_values: list[str] = Field(default_factory=list)


class AnalystReport(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    version_id: uuid.UUID | None = None
    version_label: str | None = None
    generated_at: datetime
    row_count: int
    column_count: int

    #: Deterministic executive summary, always present.
    summary: str
    semantic_columns: list[SemanticColumn] = Field(default_factory=list)
    kpis: list[AnalystKpi] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    trends: list[TrendFinding] = Field(default_factory=list)
    anomalies: list[AnomalyFinding] = Field(default_factory=list)
    segments: list[SegmentFinding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    data_quality: list[DataQualityNote] = Field(default_factory=list)

    #: True when an AI provider produced the narrative below.
    ai_available: bool = False
    #: Why the AI layer was skipped or failed, when it was.
    ai_status: str | None = None
    ai: AiNarrative | None = None
    #: Served from cache rather than recomputed.
    cached: bool = False


class AnalyzeRequest(BaseModel):
    version_id: uuid.UUID | None = None
    #: Skip the LLM and return deterministic analysis only.
    include_ai: bool = True
    #: Ignore any cached report and recompute.
    refresh: bool = False


class AnalystQuestionRequest(BaseModel):
    version_id: uuid.UUID | None = None
    question: str = Field(min_length=3, max_length=500)


class AnalystAnswerResponse(BaseModel):
    question: str
    answer: str
    #: True when the answer came from the AI provider.
    ai_available: bool = False
    ai_status: str | None = None
    #: Insight ids the answer drew on, so the user can check the figures.
    supporting_insight_ids: list[str] = Field(default_factory=list)
    contains_untraceable_numbers: bool = False
