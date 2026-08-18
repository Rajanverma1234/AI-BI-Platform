"""KPI and business-analytics schemas.

Nothing here is dataset-specific: every metric names the column it operates on,
so the same definitions work against any schema. KPI definitions are plain data
and can be persisted later without changing the engine.

Formulas are a restricted expression tree, never a user-supplied string that
gets eval'd. See :class:`FormulaNode`.
"""

from __future__ import annotations

import enum
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.visualization import FilterSet


class MetricType(enum.StrEnum):
    """Aggregations the KPI engine can compute."""

    COUNT = "count"
    DISTINCT_COUNT = "distinct_count"
    SUM = "sum"
    AVERAGE = "average"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    RANGE = "range"
    STD_DEV = "std_dev"


#: Metrics that need a numeric column. COUNT/DISTINCT_COUNT work on anything.
NUMERIC_METRICS = frozenset(
    {
        MetricType.SUM,
        MetricType.AVERAGE,
        MetricType.MEDIAN,
        MetricType.RANGE,
        MetricType.STD_DEV,
    }
)


class TimePeriod(enum.StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class SortDirection(enum.StrEnum):
    ASC = "asc"
    DESC = "desc"


class ValueFormat(enum.StrEnum):
    NUMBER = "number"
    INTEGER = "integer"
    CURRENCY = "currency"
    PERCENT = "percent"


class KpiFormat(BaseModel):
    """Presentation hints. Formatting itself happens in the frontend."""

    style: ValueFormat = ValueFormat.NUMBER
    decimals: int = Field(default=2, ge=0, le=6)
    prefix: str | None = Field(default=None, max_length=8)
    suffix: str | None = Field(default=None, max_length=8)


# --- Formula engine ----------------------------------------------------------

#: Bounds the expression tree so a deeply nested payload cannot exhaust the stack.
MAX_FORMULA_DEPTH = 8


class MetricRef(BaseModel):
    """A single aggregation used as a formula operand."""

    node: Literal["metric"] = "metric"
    metric: MetricType
    #: Not required by COUNT, which counts rows.
    column: str | None = Field(default=None, max_length=255)
    filters: FilterSet | None = None


class ConstantNode(BaseModel):
    node: Literal["constant"] = "constant"
    value: float


class BinaryOperator(enum.StrEnum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"


class BinaryNode(BaseModel):
    node: Literal["binary"] = "binary"
    operator: BinaryOperator
    left: FormulaNode
    right: FormulaNode


#: A controlled expression tree. There is no string parsing and no eval: the
#: only things a client can express are metrics, numeric constants, and the
#: four arithmetic operators.
FormulaNode = Annotated[
    MetricRef | ConstantNode | BinaryNode,
    Field(discriminator="node"),
]

BinaryNode.model_rebuild()


# --- KPI definitions ---------------------------------------------------------


class ComparisonSpec(BaseModel):
    """Compare the KPI against the preceding period."""

    date_column: str = Field(min_length=1, max_length=255)
    period: TimePeriod = TimePeriod.MONTH


class KpiDefinition(BaseModel):
    """Reusable, persistable KPI definition.

    Either ``metric`` (+ ``column``) or ``formula`` must be supplied.
    """

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    metric: MetricType | None = None
    column: str | None = Field(default=None, max_length=255)
    filters: FilterSet | None = None
    #: Optional breakdown; when set the KPI returns one value per group.
    group_by: str | None = Field(default=None, max_length=255)
    formula: FormulaNode | None = None
    format: KpiFormat = Field(default_factory=KpiFormat)
    comparison: ComparisonSpec | None = None


class KpiComparison(BaseModel):
    period: TimePeriod
    current_label: str | None = None
    previous_label: str | None = None
    previous_value: float | None = None
    absolute_change: float | None = None
    percentage_change: float | None = None


class KpiGroupValue(BaseModel):
    group: str
    value: float | None = None


class KpiResult(BaseModel):
    name: str
    description: str | None = None
    value: float | None = None
    #: False when the KPI could not be computed; `reason` explains why.
    available: bool = True
    reason: str | None = None
    metric: MetricType | None = None
    column: str | None = None
    format: KpiFormat = Field(default_factory=KpiFormat)
    comparison: KpiComparison | None = None
    groups: list[KpiGroupValue] = Field(default_factory=list)


class KpiCalculateRequest(BaseModel):
    version_id: uuid.UUID | None = None
    kpis: list[KpiDefinition] = Field(min_length=1, max_length=25)


class KpiCalculateResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    row_count: int
    results: list[KpiResult] = Field(default_factory=list)


class KpiSuggestion(BaseModel):
    """A KPI the engine can actually compute for this dataset."""

    definition: KpiDefinition
    #: Which rule produced this suggestion - never a model output.
    reason: str


class ColumnRole(BaseModel):
    """What the dataset offers, so the UI can build valid configurations."""

    name: str
    dtype: str
    #: Numeric in type. Not enough on its own to justify SUM/AVERAGE - an id
    #: column is numeric too. See `measure`.
    numeric: bool = False
    #: A numeric column that is not an identifier, so totals and averages of it
    #: are meaningful.
    measure: bool = False
    #: Usable as a grouping dimension.
    categorical: bool = False
    #: Usable as a time axis.
    temporal: bool = False
    #: Looks like an entity identifier (high-cardinality, id-like name).
    identifier: bool = False


class KpiCatalogResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    row_count: int
    columns: list[ColumnRole] = Field(default_factory=list)
    suggestions: list[KpiSuggestion] = Field(default_factory=list)
    #: KPIs that could not be offered, with the reason.
    unavailable: list[dict[str, str]] = Field(default_factory=list)


# --- Time series and growth --------------------------------------------------


class MetricSpec(BaseModel):
    """A metric applied to a column, shared by most analytics requests."""

    metric: MetricType = MetricType.SUM
    column: str | None = Field(default=None, max_length=255)


class TimeSeriesRequest(BaseModel):
    version_id: uuid.UUID | None = None
    date_column: str = Field(min_length=1, max_length=255)
    period: TimePeriod = TimePeriod.MONTH
    metric: MetricType = MetricType.SUM
    column: str | None = Field(default=None, max_length=255)
    filters: FilterSet | None = None
    #: Optional second dimension, returned as separate series.
    group_by: str | None = Field(default=None, max_length=255)
    max_points: int = Field(default=500, ge=2, le=2000)


class TimeSeriesPoint(BaseModel):
    label: str
    value: float | None = None


class TimeSeriesSeries(BaseModel):
    name: str
    points: list[TimeSeriesPoint] = Field(default_factory=list)


class TimeSeriesResponse(BaseModel):
    date_column: str
    period: TimePeriod
    metric: MetricType
    column: str | None = None
    labels: list[str] = Field(default_factory=list)
    series: list[TimeSeriesSeries] = Field(default_factory=list)
    truncated: bool = False


class GrowthRequest(BaseModel):
    version_id: uuid.UUID | None = None
    date_column: str = Field(min_length=1, max_length=255)
    period: TimePeriod = TimePeriod.MONTH
    metric: MetricType = MetricType.SUM
    column: str | None = Field(default=None, max_length=255)
    filters: FilterSet | None = None


class GrowthPoint(BaseModel):
    label: str
    value: float | None = None
    previous_value: float | None = None
    absolute_change: float | None = None
    percentage_change: float | None = None


class GrowthResponse(BaseModel):
    date_column: str
    period: TimePeriod
    metric: MetricType
    column: str | None = None
    current: GrowthPoint | None = None
    points: list[GrowthPoint] = Field(default_factory=list)
    #: Set when there are too few periods to compute growth.
    message: str | None = None


# --- Segmentation, ranking, contribution -------------------------------------


class SegmentRequest(BaseModel):
    version_id: uuid.UUID | None = None
    dimension: str = Field(min_length=1, max_length=255)
    metric: MetricType = MetricType.SUM
    column: str | None = Field(default=None, max_length=255)
    filters: FilterSet | None = None
    sort: SortDirection = SortDirection.DESC
    limit: int = Field(default=20, ge=1, le=500)


class SegmentRow(BaseModel):
    label: str
    value: float | None = None
    #: Share of the total across all groups, before any limit was applied.
    percentage: float | None = None


class SegmentResponse(BaseModel):
    dimension: str
    metric: MetricType
    column: str | None = None
    total: float | None = None
    rows: list[SegmentRow] = Field(default_factory=list)
    group_count: int = 0
    truncated: bool = False


class RankingRequest(SegmentRequest):
    """Top-N / bottom-N ranking. `sort` selects which end."""


class ContributionRow(SegmentRow):
    cumulative_percentage: float | None = None


class ContributionResponse(BaseModel):
    dimension: str
    metric: MetricType
    column: str | None = None
    total: float | None = None
    rows: list[ContributionRow] = Field(default_factory=list)
    group_count: int = 0


# --- ABC analysis ------------------------------------------------------------


class AbcRequest(BaseModel):
    version_id: uuid.UUID | None = None
    dimension: str = Field(min_length=1, max_length=255)
    metric: MetricType = MetricType.SUM
    column: str | None = Field(default=None, max_length=255)
    filters: FilterSet | None = None
    #: Cumulative-contribution cut-offs; configurable, not hardcoded.
    a_threshold: float = Field(default=80.0, gt=0, lt=100)
    b_threshold: float = Field(default=95.0, gt=0, le=100)


class AbcRow(BaseModel):
    label: str
    value: float
    percentage: float
    cumulative_percentage: float
    abc_class: Literal["A", "B", "C"]


class AbcClassSummary(BaseModel):
    abc_class: Literal["A", "B", "C"]
    item_count: int
    total_value: float
    percentage_of_total: float
    percentage_of_items: float


class AbcResponse(BaseModel):
    dimension: str
    metric: MetricType
    column: str | None = None
    total: float
    a_threshold: float
    b_threshold: float
    rows: list[AbcRow] = Field(default_factory=list)
    summary: list[AbcClassSummary] = Field(default_factory=list)


# --- Entity analysis ---------------------------------------------------------


class EntityRequest(BaseModel):
    version_id: uuid.UUID | None = None
    #: Any identifier column - never assumed to be "customer_id".
    entity_column: str = Field(min_length=1, max_length=255)
    #: Optional monetary/numeric column for per-entity value.
    value_column: str | None = Field(default=None, max_length=255)
    #: Optional transaction identifier for per-entity counts.
    transaction_column: str | None = Field(default=None, max_length=255)
    filters: FilterSet | None = None
    limit: int = Field(default=20, ge=1, le=500)


class EntityRow(BaseModel):
    entity: str
    record_count: int
    transaction_count: int | None = None
    total_value: float | None = None
    average_value: float | None = None


class EntityResponse(BaseModel):
    entity_column: str
    value_column: str | None = None
    unique_entities: int
    repeat_entities: int
    one_time_entities: int
    average_records_per_entity: float | None = None
    average_value_per_entity: float | None = None
    top_entities: list[EntityRow] = Field(default_factory=list)


# --- Distribution ------------------------------------------------------------


class DistributionRequest(BaseModel):
    version_id: uuid.UUID | None = None
    column: str = Field(min_length=1, max_length=255)
    filters: FilterSet | None = None
    bins: int = Field(default=10, ge=2, le=100)


class DistributionBucket(BaseModel):
    label: str
    count: int
    lower: float
    upper: float


class DistributionResponse(BaseModel):
    column: str
    count: int
    mean: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    std_dev: float | None = None
    percentiles: dict[str, float | None] = Field(default_factory=dict)
    buckets: list[DistributionBucket] = Field(default_factory=list)


class AnalyticsMeta(BaseModel):
    """Echoed on every analytics response so the UI can label the source."""

    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    row_count: int
    filtered_row_count: int


class TimeSeriesEnvelope(BaseModel):
    meta: AnalyticsMeta
    result: TimeSeriesResponse


class GrowthEnvelope(BaseModel):
    meta: AnalyticsMeta
    result: GrowthResponse


class SegmentEnvelope(BaseModel):
    meta: AnalyticsMeta
    result: SegmentResponse


class ContributionEnvelope(BaseModel):
    meta: AnalyticsMeta
    result: ContributionResponse


class AbcEnvelope(BaseModel):
    meta: AnalyticsMeta
    result: AbcResponse


class EntityEnvelope(BaseModel):
    meta: AnalyticsMeta
    result: EntityResponse


class DistributionEnvelope(BaseModel):
    meta: AnalyticsMeta
    result: DistributionResponse


AnyAnalyticsResult = dict[str, Any]
