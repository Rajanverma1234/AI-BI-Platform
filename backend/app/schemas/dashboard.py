"""Dashboard schemas.

Widget configurations are the security boundary of this feature, so they are
built from the models the rest of the platform already validates: a chart
widget carries the existing chart fields, a KPI widget an existing
:class:`KpiDefinition`, a table widget the existing query fields. A widget can
therefore name a column, a metric, an aggregation and a filter - and nothing
else. There is no field anywhere in this module that accepts an expression, a
query string or a code fragment.

Configurations are a discriminated union on ``widget_type``, so a chart
widget's payload cannot be posted to a KPI widget: Pydantic rejects it before
any service sees it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.models.dashboard import WidgetType
from app.schemas.analytics import KpiDefinition, KpiResult, MetricType, TimePeriod
from app.schemas.common import ORMModel, Page
from app.schemas.insights import BusinessInsight, Recommendation
from app.schemas.visualization import (
    Aggregation,
    ChartDataResponse,
    ChartType,
    FilterSet,
)

#: Grid width. Four columns is the widest layout the UI offers.
MIN_LAYOUT_COLUMNS = 1
MAX_LAYOUT_COLUMNS = 4
#: Widgets per dashboard. Every widget costs a resolution pass on refresh.
MAX_WIDGETS = 40
#: Rows a table widget may return. Dashboards summarise; they are not exports.
MAX_TABLE_ROWS = 200


class WidgetStatus(enum.StrEnum):
    OK = "ok"
    #: The widget could not be resolved. The rest of the dashboard still loads.
    ERROR = "error"


class AdvancedAnalysis(enum.StrEnum):
    """Advanced analytics a widget may embed, by name only."""

    RFM = "rfm"
    COHORT = "cohort"
    CHURN = "churn"
    FORECAST = "forecast"
    PARETO = "pareto"
    SEGMENTATION = "segmentation"


# --- Widget configuration ----------------------------------------------------


class KpiWidgetConfig(BaseModel):
    """Reuses the existing KPI definition, so no metric logic is restated."""

    widget_type: Literal[WidgetType.KPI] = WidgetType.KPI
    definition: KpiDefinition


class ChartWidgetConfig(BaseModel):
    """The existing chart fields. One charting pipeline, reused as-is."""

    widget_type: Literal[WidgetType.CHART] = WidgetType.CHART
    chart_type: ChartType
    x_column: str | None = Field(default=None, max_length=255)
    y_column: str | None = Field(default=None, max_length=255)
    group_by: str | None = Field(default=None, max_length=255)
    aggregation: Aggregation = Aggregation.SUM
    filters: FilterSet | None = None
    #: Date granularity, when the x axis is a date column.
    period: TimePeriod | None = None
    bins: int = Field(default=10, ge=2, le=100)
    max_categories: int = Field(default=25, ge=1, le=100)
    x_axis_label: str | None = Field(default=None, max_length=255)
    y_axis_label: str | None = Field(default=None, max_length=255)


class TableAggregation(BaseModel):
    column: str = Field(min_length=1, max_length=255)
    aggregation: Aggregation
    alias: str | None = Field(default=None, max_length=255)


class TableWidgetConfig(BaseModel):
    """A bounded, aggregated table - never a raw dump of the dataset."""

    widget_type: Literal[WidgetType.TABLE] = WidgetType.TABLE
    group_by: list[str] = Field(default_factory=list, max_length=3)
    aggregations: list[TableAggregation] = Field(default_factory=list, max_length=10)
    #: Plain column projection, used when no grouping is requested.
    columns: list[str] = Field(default_factory=list, max_length=20)
    filters: FilterSet | None = None
    sort_by: str | None = Field(default=None, max_length=255)
    sort_desc: bool = True
    limit: int = Field(default=20, ge=1, le=MAX_TABLE_ROWS)


class AiInsightWidgetConfig(BaseModel):
    """Points at an existing insight run; never generates a second one."""

    widget_type: Literal[WidgetType.AI_INSIGHT] = WidgetType.AI_INSIGHT
    #: Null means "the latest run for this dataset".
    run_id: uuid.UUID | None = None
    #: Optional narrowing, using the categories the insight engine defines.
    categories: list[str] = Field(default_factory=list, max_length=10)
    priorities: list[str] = Field(default_factory=list, max_length=4)
    #: Show specific findings by id, when the author pinned them.
    insight_ids: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=5, ge=1, le=20)
    #: Show the business health score alongside the findings.
    show_health: bool = False


class RecommendationWidgetConfig(BaseModel):
    widget_type: Literal[WidgetType.RECOMMENDATION] = WidgetType.RECOMMENDATION
    run_id: uuid.UUID | None = None
    priorities: list[str] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=5, ge=1, le=20)


class TextWidgetConfig(BaseModel):
    """Plain text. Rendered as text by the UI, never as HTML."""

    widget_type: Literal[WidgetType.TEXT] = WidgetType.TEXT
    content: str = Field(default="", max_length=5000)


class NlqWidgetConfig(BaseModel):
    """Replays a previously recorded, already-validated query plan.

    The widget stores only the id of a saved NLQ query. The plan is re-read
    from the database and re-validated against the current frame before it
    runs, so a plan that no longer fits the data fails safely rather than
    executing against the wrong columns.
    """

    widget_type: Literal[WidgetType.NLQ_RESULT] = WidgetType.NLQ_RESULT
    nlq_query_id: uuid.UUID
    #: Render the result as a chart when the plan recommends one.
    show_chart: bool = True


class AdvancedWidgetConfig(BaseModel):
    """Embeds one advanced analysis, selected by name."""

    widget_type: Literal[WidgetType.ADVANCED] = WidgetType.ADVANCED
    analysis: AdvancedAnalysis
    #: Column overrides; omitted means "use the detected column for the role".
    dimension: str | None = Field(default=None, max_length=255)
    column: str | None = Field(default=None, max_length=255)
    metric: MetricType = MetricType.SUM
    period: TimePeriod = TimePeriod.MONTH
    horizon: int = Field(default=6, ge=1, le=36)
    clusters: int = Field(default=4, ge=2, le=10)
    limit: int = Field(default=10, ge=1, le=100)
    filters: FilterSet | None = None


#: Discriminated on widget_type, so each widget can only carry its own shape.
WidgetConfig = Annotated[
    KpiWidgetConfig
    | ChartWidgetConfig
    | TableWidgetConfig
    | AiInsightWidgetConfig
    | RecommendationWidgetConfig
    | TextWidgetConfig
    | NlqWidgetConfig
    | AdvancedWidgetConfig,
    Field(discriminator="widget_type"),
]


# --- Layout ------------------------------------------------------------------


class WidgetPosition(BaseModel):
    """Grid position, in columns. Never pixels, so layouts reflow."""

    x: int = Field(default=0, ge=0, le=MAX_LAYOUT_COLUMNS - 1)
    y: int = Field(default=0, ge=0, le=200)
    width: int = Field(default=1, ge=1, le=MAX_LAYOUT_COLUMNS)
    #: Height in grid rows; drives the rendered widget height.
    height: int = Field(default=1, ge=1, le=4)


# --- Requests ----------------------------------------------------------------


class WidgetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    position: WidgetPosition = Field(default_factory=WidgetPosition)
    configuration: WidgetConfig


class WidgetUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    position: WidgetPosition | None = None
    #: Replaces the configuration wholesale; partial merges are not supported
    #: because a half-updated configuration may not be valid.
    configuration: WidgetConfig | None = None


class LayoutItem(BaseModel):
    """One entry in a bulk layout save, so a drag saves in a single request."""

    widget_id: uuid.UUID
    position: WidgetPosition


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID | None = None
    layout_columns: int = Field(
        default=2, ge=MIN_LAYOUT_COLUMNS, le=MAX_LAYOUT_COLUMNS
    )
    #: Start from a template, adapted to this dataset's own columns.
    template: str | None = Field(default=None, max_length=40)


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    layout_columns: int | None = Field(
        default=None, ge=MIN_LAYOUT_COLUMNS, le=MAX_LAYOUT_COLUMNS
    )
    filters: FilterSet | None = None
    #: Moving to another version is explicit, never automatic.
    dataset_version_id: uuid.UUID | None = None
    #: Set when the caller means "go back to the original upload".
    clear_version: bool = False
    layout: list[LayoutItem] | None = Field(default=None, max_length=MAX_WIDGETS)


class DashboardDuplicate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class DashboardRefreshRequest(BaseModel):
    """Ad-hoc filters layered over the dashboard's saved ones.

    Cross-widget filtering uses this: clicking a bar sends the clicked
    dimension and value here rather than mutating the saved dashboard.
    """

    filters: FilterSet | None = None
    #: Resolve only these widgets. Used by "refresh this widget".
    widget_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_WIDGETS)


# --- Responses ---------------------------------------------------------------


class WidgetResponse(BaseModel):
    id: uuid.UUID
    dashboard_id: uuid.UUID
    widget_type: WidgetType
    title: str
    position: WidgetPosition
    configuration: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DashboardResponse(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    layout_columns: int
    filters: dict[str, Any] | None = None
    widget_count: int = 0
    created_at: datetime
    updated_at: datetime


class DashboardDetail(BaseModel):
    dashboard: DashboardResponse
    #: Human-readable source, e.g. "v2 - outliers removed".
    version_label: str
    dataset_name: str
    widgets: list[WidgetResponse] = Field(default_factory=list)


#: Paginated envelope returned by GET .../dashboards.
DashboardListResponse = Page[DashboardResponse]


class KpiWidgetData(BaseModel):
    result: KpiResult


class TableWidgetData(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class InsightWidgetData(BaseModel):
    insights: list[BusinessInsight] = Field(default_factory=list)
    health_score: int | None = None
    health_rating: str | None = None
    #: Which run these came from, so the widget can say how current it is.
    run_id: uuid.UUID | None = None
    generated_at: datetime | None = None
    stale: bool = False


class RecommendationWidgetData(BaseModel):
    recommendations: list[Recommendation] = Field(default_factory=list)
    run_id: uuid.UUID | None = None
    generated_at: datetime | None = None


class NlqWidgetData(BaseModel):
    question: str
    answer: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    metric_label: str | None = None
    metric_value: float | None = None
    chart: ChartDataResponse | None = None


class TextWidgetData(BaseModel):
    content: str


class AdvancedWidgetData(BaseModel):
    analysis: AdvancedAnalysis
    #: Headline figures for the analysis, already formatted.
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart: ChartDataResponse | None = None
    note: str | None = None


class WidgetResult(BaseModel):
    """One resolved widget.

    A failure is carried here rather than raised, so a single broken widget
    never costs the user the rest of the dashboard.
    """

    widget_id: uuid.UUID
    widget_type: WidgetType
    title: str
    position: WidgetPosition
    status: WidgetStatus = WidgetStatus.OK
    #: Safe, user-facing reason. Never a traceback or a path.
    error: str | None = None

    kpi: KpiWidgetData | None = None
    chart: ChartDataResponse | None = None
    table: TableWidgetData | None = None
    insight: InsightWidgetData | None = None
    recommendation: RecommendationWidgetData | None = None
    text: TextWidgetData | None = None
    nlq: NlqWidgetData | None = None
    advanced: AdvancedWidgetData | None = None


class DashboardData(BaseModel):
    """A fully resolved dashboard, ready to render."""

    dashboard_id: uuid.UUID
    name: str
    description: str | None = None
    dataset_id: uuid.UUID
    dataset_name: str
    version_id: uuid.UUID | None = None
    #: Always shown in the header: a dashboard states the data it is built on.
    version_label: str
    layout_columns: int
    row_count: int
    refreshed_at: datetime
    #: The saved filters merged with any ad-hoc ones from this request.
    applied_filters: dict[str, Any] | None = None
    filtered_row_count: int
    widgets: list[WidgetResult] = Field(default_factory=list)


# --- Filters and templates ---------------------------------------------------


class FilterField(BaseModel):
    """One filterable column, described from the dataset's own metadata."""

    column: str
    kind: Literal["categorical", "numeric", "date"]
    #: Distinct values, for categorical columns only.
    values: list[str] = Field(default_factory=list)
    minimum: str | float | None = None
    maximum: str | float | None = None
    #: The business role detected for this column, when there is one.
    role: str | None = None


class DashboardFilterOptions(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    fields: list[FilterField] = Field(default_factory=list)


class TemplateWidget(BaseModel):
    title: str
    position: WidgetPosition
    configuration: WidgetConfig


class DashboardTemplate(BaseModel):
    key: str
    name: str
    description: str
    layout_columns: int = 2
    #: Only the widgets this dataset can actually support.
    widgets: list[TemplateWidget] = Field(default_factory=list)
    #: What the template would also have included, and why it could not.
    unavailable: list[dict[str, str]] = Field(default_factory=list)


class DashboardTemplateList(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    templates: list[DashboardTemplate] = Field(default_factory=list)
    #: Suggested starter widgets for an empty dashboard, adapted to the schema.
    suggestions: list[TemplateWidget] = Field(default_factory=list)
