"""Natural-language query schemas.

The central idea is the :class:`QueryPlan`: the LLM never writes SQL or Python,
it fills in this structure. The plan is then validated against the dataset's
real columns and executed by a deterministic executor, so the model's output
can only ever select a column, an aggregation and a filter that already exist.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.analytics import MetricType, TimePeriod
from app.schemas.visualization import ChartType, FilterLogic, FilterOperator

#: Hard ceilings so a plan can never ask for an unbounded result.
MAX_RESULT_ROWS = 500
DEFAULT_RESULT_ROWS = 50
MAX_MEASURES = 5
MAX_DIMENSIONS = 2
MAX_FILTERS = 10
#: How many earlier turns are replayed to the planner for follow-up questions.
MAX_CONTEXT_TURNS = 3


class QueryIntent(enum.StrEnum):
    """Shape of the answer, which determines how the plan is executed."""

    METRIC = "metric"
    GROUP = "group"
    RANK = "rank"
    TIMESERIES = "timeseries"
    COMPARISON = "comparison"
    MULTI_METRIC = "multi_metric"


class PlanMeasure(BaseModel):
    aggregation: MetricType
    #: None is only valid for COUNT, which counts rows.
    column: str | None = Field(default=None, max_length=255)
    alias: str | None = Field(default=None, max_length=120)

    @property
    def label(self) -> str:
        if self.alias:
            return self.alias
        if self.column is None:
            return "count"
        return f"{self.aggregation.value}_{self.column}"


class PlanFilter(BaseModel):
    column: str = Field(min_length=1, max_length=255)
    operator: FilterOperator
    value: Any | None = None
    value_to: Any | None = None


class QueryPlan(BaseModel):
    """A structured, validatable description of what to compute."""

    intent: QueryIntent
    measures: list[PlanMeasure] = Field(default_factory=list, max_length=MAX_MEASURES)
    dimensions: list[str] = Field(default_factory=list, max_length=MAX_DIMENSIONS)
    #: Time axis, required by the timeseries intent.
    date_column: str | None = Field(default=None, max_length=255)
    date_period: TimePeriod | None = None
    filters: list[PlanFilter] = Field(default_factory=list, max_length=MAX_FILTERS)
    filter_logic: FilterLogic = FilterLogic.AND
    sort_by: str | None = Field(default=None, max_length=255)
    sort_desc: bool = True
    limit: int = Field(default=DEFAULT_RESULT_ROWS, ge=1, le=MAX_RESULT_ROWS)
    chart_type: ChartType | None = None


class PlannerOutput(BaseModel):
    """What the planner returns - either a plan, or a request for clarification."""

    plan: QueryPlan | None = None
    #: Set when the question cannot be mapped confidently onto real columns.
    clarification_needed: bool = False
    clarification_question: str | None = None
    #: Which columns the planner was torn between, to help the user choose.
    candidate_columns: list[str] = Field(default_factory=list)
    #: How the plan was produced: "ai" or "rules".
    source: str = "rules"
    notes: str | None = None


class ResultColumn(BaseModel):
    name: str
    #: "dimension" or "measure"; drives table formatting and chart mapping.
    role: str


class QueryResult(BaseModel):
    result_type: QueryIntent
    columns: list[ResultColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    #: Populated for single-metric answers.
    metric_label: str | None = None
    metric_value: float | None = None
    truncated: bool = False


class CalculationStep(BaseModel):
    """One line of the auditable 'how this was calculated' breakdown."""

    label: str
    detail: str


class ChartRecommendation(BaseModel):
    chart_type: ChartType
    reason: str
    #: Ready for the existing ChartRenderer; no new chart engine.
    x_axis: str | None = None
    y_axis: str | None = None
    labels: list[str] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)


class QueryContextTurn(BaseModel):
    """One earlier turn, replayed so follow-ups keep their subject."""

    question: str
    plan: QueryPlan | None = None


class NlqRequest(BaseModel):
    version_id: uuid.UUID | None = None
    question: str = Field(min_length=1, max_length=500)
    #: Bounded conversation context for follow-up questions.
    context: list[QueryContextTurn] = Field(default_factory=list, max_length=MAX_CONTEXT_TURNS)


class NlqResponse(BaseModel):
    question: str
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    #: False when the question needs clarification or could not be executed.
    success: bool
    answer: str
    plan: QueryPlan | None = None
    result: QueryResult | None = None
    calculation: list[CalculationStep] = Field(default_factory=list)
    chart: ChartRecommendation | None = None

    clarification_needed: bool = False
    clarification_question: str | None = None
    candidate_columns: list[str] = Field(default_factory=list)

    #: True when the AI produced the plan and/or the wording.
    ai_available: bool = False
    ai_status: str | None = None
    #: "ai" or "rules" - how the plan was built.
    plan_source: str = "rules"
    #: Flags any number in the AI wording not found in the executed result.
    contains_untraceable_numbers: bool = False
    generated_at: datetime


class QueryHistoryEntry(BaseModel):
    id: uuid.UUID
    question: str
    status: str
    error_message: str | None = None
    plan: dict[str, Any] | None = None
    dataset_version_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QuerySuggestion(BaseModel):
    question: str
    #: The deterministic rule that produced it.
    reason: str


class QuerySuggestionsResponse(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    suggestions: list[QuerySuggestion] = Field(default_factory=list)


class QueryStatus(enum.StrEnum):
    SUCCESS = "success"
    CLARIFICATION = "clarification"
    FAILED = "failed"


#: Literal alias kept for the ORM column definition.
QueryStatusLiteral = Literal["success", "clarification", "failed"]
