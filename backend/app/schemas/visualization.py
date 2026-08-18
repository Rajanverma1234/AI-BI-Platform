"""Preview, query, chart and EDA schemas.

Filters and chart configuration are structured objects, never fragments of a
query language. Nothing here is interpolated into SQL or eval'd - the service
layer maps each operator onto a pandas expression after checking the column
exists and the type is compatible.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.profiling import DetectedType

#: Bounds on how much data a single request may return.
MAX_PREVIEW_ROWS = 200
DEFAULT_PREVIEW_ROWS = 50
MAX_QUERY_ROWS = 5000
MAX_CHART_CATEGORIES = 200
MAX_FILTERS = 20


class FilterOperator(enum.StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    BETWEEN = "between"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class FilterLogic(enum.StrEnum):
    AND = "and"
    OR = "or"


class Aggregation(enum.StrEnum):
    COUNT = "count"
    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"


class ChartType(enum.StrEnum):
    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    DONUT = "donut"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    BOX = "box"


#: Aggregations that require a numeric column. COUNT works on any type.
NUMERIC_ONLY_AGGREGATIONS = frozenset(
    {
        Aggregation.SUM,
        Aggregation.MEAN,
        Aggregation.MEDIAN,
    }
)


class FilterCondition(BaseModel):
    column: str = Field(min_length=1, max_length=255)
    operator: FilterOperator
    #: Ignored by is_null / is_not_null.
    value: Any | None = None
    #: Second bound, required by `between`.
    value_to: Any | None = None


class FilterSet(BaseModel):
    """A flat list of conditions combined with a single logic operator.

    Deliberately not nestable: one level covers the cases this phase needs and
    keeps validation - and the UI - simple.
    """

    logic: FilterLogic = FilterLogic.AND
    conditions: list[FilterCondition] = Field(default_factory=list, max_length=MAX_FILTERS)


# --- Preview -----------------------------------------------------------------


class PreviewColumn(BaseModel):
    name: str
    dtype: DetectedType


class DataPreviewResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    columns: list[PreviewColumn]
    #: Null cells are serialised as JSON null so the UI can mark them.
    rows: list[dict[str, Any]]
    total_rows: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


# --- Query -------------------------------------------------------------------


class AggregationSpec(BaseModel):
    column: str = Field(min_length=1, max_length=255)
    aggregation: Aggregation
    #: Output column name; defaults to "<agg>_<column>".
    alias: str | None = Field(default=None, max_length=255)


class QueryRequest(BaseModel):
    version_id: uuid.UUID | None = None
    filters: FilterSet | None = None
    #: Columns to group by. Empty means aggregate over the whole dataset.
    group_by: list[str] = Field(default_factory=list, max_length=3)
    aggregations: list[AggregationSpec] = Field(default_factory=list, max_length=10)
    #: Columns to return when no aggregation is requested.
    columns: list[str] = Field(default_factory=list, max_length=50)
    sort_by: str | None = None
    sort_desc: bool = False
    limit: int = Field(default=100, ge=1, le=MAX_QUERY_ROWS)


class QueryResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    #: Rows matching the filters before `limit` was applied.
    total_matched: int
    truncated: bool


# --- Charts ------------------------------------------------------------------


class ChartConfig(BaseModel):
    """Reusable chart definition, kept extensible for future dashboards."""

    version_id: uuid.UUID | None = None
    chart_type: ChartType
    #: Category / X column. Not used by histogram or single-column box plots.
    x_column: str | None = Field(default=None, max_length=255)
    #: Value / Y column.
    y_column: str | None = Field(default=None, max_length=255)
    #: Optional second grouping, rendered as multiple series.
    group_by: str | None = Field(default=None, max_length=255)
    aggregation: Aggregation = Aggregation.SUM
    filters: FilterSet | None = None
    title: str | None = Field(default=None, max_length=255)
    x_axis_label: str | None = Field(default=None, max_length=255)
    y_axis_label: str | None = Field(default=None, max_length=255)
    #: Histogram only.
    bins: int = Field(default=10, ge=2, le=100)
    #: Maximum categories before the rest are grouped into "Other".
    max_categories: int = Field(default=25, ge=1, le=MAX_CHART_CATEGORIES)


class ChartSeries(BaseModel):
    name: str
    data: list[float | None]


class ScatterPoint(BaseModel):
    x: float
    y: float


class BoxPlotStats(BaseModel):
    label: str
    minimum: float
    q1: float
    median: float
    q3: float
    maximum: float
    outlier_count: int


class ChartDataResponse(BaseModel):
    """Structured chart data. Presentation lives entirely in the frontend."""

    chart_type: ChartType
    title: str | None = None
    x_axis: str | None = None
    y_axis: str | None = None
    #: Category labels, aligned with each series' data array.
    labels: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    #: Populated for scatter charts instead of labels/series.
    points: list[ScatterPoint] = Field(default_factory=list)
    #: Populated for box plots.
    boxes: list[BoxPlotStats] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- EDA and correlation -----------------------------------------------------


class NumericSummary(BaseModel):
    column: str
    mean: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    std_dev: float | None = None


class CategoricalSummary(BaseModel):
    column: str
    unique_count: int
    top_values: list[dict[str, Any]] = Field(default_factory=list)


class DateSummary(BaseModel):
    column: str
    minimum: str | None = None
    maximum: str | None = None
    #: Span between the earliest and latest value, in days.
    range_days: int | None = None


class EdaSummaryResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    row_count: int
    numeric: list[NumericSummary] = Field(default_factory=list)
    categorical: list[CategoricalSummary] = Field(default_factory=list)
    dates: list[DateSummary] = Field(default_factory=list)


class CorrelationResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    method: str = "pearson"
    columns: list[str] = Field(default_factory=list)
    #: Row-major square matrix aligned with `columns`; null where undefined.
    matrix: list[list[float | None]] = Field(default_factory=list)
    #: Columns excluded from the matrix, with the reason.
    excluded: list[dict[str, str]] = Field(default_factory=list)
    message: str | None = None


class ChartSuggestion(BaseModel):
    chart_type: ChartType
    title: str
    #: Why this chart was suggested - a rule name, never a model output.
    reason: str
    config: ChartConfig


class ChartSuggestionsResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    suggestions: list[ChartSuggestion] = Field(default_factory=list)
