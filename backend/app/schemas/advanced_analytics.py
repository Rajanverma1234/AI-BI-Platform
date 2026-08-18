"""Advanced analytics schemas.

Only the analyses that did not already exist get new schemas here. ABC,
correlation, distribution/statistics and contribution already have endpoints
and schemas from earlier phases and are reused rather than redefined.

Every request takes explicit column overrides: detection is a convenience, not
an assumption, and the user can always correct it.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.analytics import MetricType, TimePeriod
from app.schemas.visualization import FilterSet


class AnalysisMeta(BaseModel):
    """Echoed by every advanced analysis so the UI can show its provenance."""

    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    row_count: int
    #: Which column was used for each role, after detection and overrides.
    columns_used: dict[str, str] = Field(default_factory=dict)
    #: Non-fatal caveats worth showing the user.
    warnings: list[str] = Field(default_factory=list)


class RequirementError(BaseModel):
    """Returned when an analysis cannot run for want of suitable columns."""

    analysis: str
    message: str
    required_roles: list[str] = Field(default_factory=list)
    missing_roles: list[str] = Field(default_factory=list)


# --- RFM ---------------------------------------------------------------------


class RfmSegment(enum.StrEnum):
    CHAMPIONS = "Champions"
    LOYAL = "Loyal Customers"
    POTENTIAL_LOYALIST = "Potential Loyalists"
    NEW = "New Customers"
    AT_RISK = "At Risk"
    CANT_LOSE = "Can't Lose Them"
    HIBERNATING = "Hibernating"
    LOST = "Lost Customers"
    OTHERS = "Others"


class RfmRequest(BaseModel):
    version_id: uuid.UUID | None = None
    customer_column: str | None = None
    date_column: str | None = None
    monetary_column: str | None = None
    filters: FilterSet | None = None
    #: Rows returned in the customer-level table.
    limit: int = Field(default=100, ge=1, le=1000)
    segment: RfmSegment | None = None


class RfmCustomer(BaseModel):
    customer: str
    recency_days: int
    frequency: int
    monetary: float
    r_score: int
    f_score: int
    m_score: int
    rfm_score: str
    segment: RfmSegment


class RfmSegmentSummary(BaseModel):
    segment: RfmSegment
    customer_count: int
    percentage: float
    total_monetary: float
    monetary_percentage: float
    average_recency_days: float
    average_frequency: float
    average_monetary: float


class RfmResponse(BaseModel):
    meta: AnalysisMeta
    reference_date: str
    customer_count: int
    total_monetary: float
    segments: list[RfmSegmentSummary] = Field(default_factory=list)
    customers: list[RfmCustomer] = Field(default_factory=list)
    #: Distribution of scores 1-5 for each dimension.
    score_distribution: dict[str, dict[str, int]] = Field(default_factory=dict)


# --- Clustering --------------------------------------------------------------


class SegmentationRequest(BaseModel):
    version_id: uuid.UUID | None = None
    #: Numeric feature columns; auto-selected from measures when omitted.
    feature_columns: list[str] = Field(default_factory=list, max_length=10)
    #: Aggregate to one row per entity before clustering, when supplied.
    entity_column: str | None = None
    clusters: int = Field(default=4, ge=2, le=10)
    standardize: bool = True
    filters: FilterSet | None = None
    limit: int = Field(default=500, ge=1, le=2000)


class ClusterProfile(BaseModel):
    cluster: int
    size: int
    percentage: float
    #: Mean of each feature within the cluster.
    averages: dict[str, float] = Field(default_factory=dict)
    #: How this cluster differs from the overall mean, in standard deviations.
    distinguishing_features: list[dict[str, Any]] = Field(default_factory=list)


class ClusterPoint(BaseModel):
    label: str
    cluster: int
    x: float
    y: float


class SegmentationResponse(BaseModel):
    meta: AnalysisMeta
    features: list[str]
    clusters: int
    standardized: bool
    #: Share of variance the two plotted components capture.
    explained_variance: float | None = None
    iterations: int
    profiles: list[ClusterProfile] = Field(default_factory=list)
    points: list[ClusterPoint] = Field(default_factory=list)


# --- Cohort ------------------------------------------------------------------


class CohortRequest(BaseModel):
    version_id: uuid.UUID | None = None
    customer_column: str | None = None
    date_column: str | None = None
    period: TimePeriod = TimePeriod.MONTH
    filters: FilterSet | None = None
    max_periods: int = Field(default=12, ge=2, le=36)


class CohortRow(BaseModel):
    cohort: str
    cohort_size: int
    #: Retained customer counts by period offset (index 0 = the cohort period).
    values: list[int | None] = Field(default_factory=list)
    percentages: list[float | None] = Field(default_factory=list)


class CohortResponse(BaseModel):
    meta: AnalysisMeta
    period: TimePeriod
    period_labels: list[str] = Field(default_factory=list)
    rows: list[CohortRow] = Field(default_factory=list)
    #: Average retention per offset across all cohorts.
    average_retention: list[float | None] = Field(default_factory=list)


# --- Churn -------------------------------------------------------------------


class ChurnStatus(enum.StrEnum):
    ACTIVE = "active"
    AT_RISK = "at_risk"
    CHURNED = "churned"


class ChurnRequest(BaseModel):
    version_id: uuid.UUID | None = None
    customer_column: str | None = None
    date_column: str | None = None
    monetary_column: str | None = None
    #: Days of inactivity after which a customer counts as churned.
    churn_days: int = Field(default=90, ge=1, le=1825)
    #: Days of inactivity that mark a customer as at risk.
    at_risk_days: int = Field(default=45, ge=1, le=1825)
    filters: FilterSet | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ChurnCustomer(BaseModel):
    customer: str
    last_activity: str
    days_since_activity: int
    transactions: int
    monetary: float | None = None
    status: ChurnStatus


class ChurnTrendPoint(BaseModel):
    period: str
    active_customers: int


class ChurnResponse(BaseModel):
    meta: AnalysisMeta
    #: Always "rule_based" here - no model is trained, nothing is predicted.
    method: str = "rule_based"
    method_note: str
    reference_date: str
    churn_days: int
    at_risk_days: int
    total_customers: int
    active_customers: int
    at_risk_customers: int
    churned_customers: int
    churn_rate: float
    revenue_at_risk: float | None = None
    customers: list[ChurnCustomer] = Field(default_factory=list)
    trend: list[ChurnTrendPoint] = Field(default_factory=list)


# --- Forecasting -------------------------------------------------------------


class ForecastMethod(enum.StrEnum):
    #: Holt's linear trend (double exponential smoothing).
    HOLT = "holt"
    #: Simple exponential smoothing, no trend term.
    SES = "ses"
    MOVING_AVERAGE = "moving_average"


class ForecastRequest(BaseModel):
    version_id: uuid.UUID | None = None
    date_column: str | None = None
    metric_column: str | None = None
    metric: MetricType = MetricType.SUM
    period: TimePeriod = TimePeriod.MONTH
    horizon: int = Field(default=6, ge=1, le=36)
    method: ForecastMethod = ForecastMethod.HOLT
    filters: FilterSet | None = None


class ForecastPoint(BaseModel):
    period: str
    value: float | None = None
    #: Present only on forecast rows.
    lower_bound: float | None = None
    upper_bound: float | None = None
    is_forecast: bool = False


class ForecastResponse(BaseModel):
    meta: AnalysisMeta
    method: ForecastMethod
    period: TimePeriod
    horizon: int
    periods_observed: int
    #: Direction of the fitted trend component.
    trend: str
    #: In-sample mean absolute error, so the user can judge reliability.
    mean_absolute_error: float | None = None
    confidence_level: float = 0.95
    history: list[ForecastPoint] = Field(default_factory=list)
    forecast: list[ForecastPoint] = Field(default_factory=list)


# --- Outliers and Pareto (thin wrappers over existing engines) ---------------


class OutlierRequest(BaseModel):
    version_id: uuid.UUID | None = None
    column: str
    method: str = Field(default="iqr", pattern="^(iqr|zscore)$")
    threshold: float = Field(default=1.5, gt=0, le=10)
    filters: FilterSet | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class OutlierResponse(BaseModel):
    meta: AnalysisMeta
    column: str
    method: str
    threshold: float
    total_observations: int
    outlier_count: int
    outlier_percentage: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    #: Five-number summary for the box plot, reusing the existing renderer.
    minimum: float | None = None
    q1: float | None = None
    median: float | None = None
    q3: float | None = None
    maximum: float | None = None
    outliers: list[dict[str, Any]] = Field(default_factory=list)


class ParetoRequest(BaseModel):
    version_id: uuid.UUID | None = None
    dimension: str
    metric: MetricType = MetricType.SUM
    column: str | None = None
    filters: FilterSet | None = None
    #: Cumulative share that defines the "vital few".
    threshold: float = Field(default=80.0, gt=0, lt=100)
    limit: int = Field(default=50, ge=1, le=500)


class ParetoRow(BaseModel):
    label: str
    value: float
    percentage: float
    cumulative_percentage: float
    within_threshold: bool


class ParetoResponse(BaseModel):
    meta: AnalysisMeta
    dimension: str
    metric: MetricType
    column: str | None = None
    total: float
    threshold: float
    #: Entities responsible for `threshold`% of the metric.
    vital_few_count: int
    vital_few_percentage_of_items: float
    rows: list[ParetoRow] = Field(default_factory=list)


class AdvancedCapabilities(BaseModel):
    """Which analyses this dataset can support, and why not when it cannot."""

    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    detected_columns: dict[str, str] = Field(default_factory=dict)
    available: list[str] = Field(default_factory=list)
    unavailable: list[RequirementError] = Field(default_factory=list)
