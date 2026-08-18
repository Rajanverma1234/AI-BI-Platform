"""Turning a question into a validated QueryPlan.

Two planners, same output contract:

* the AI planner asks the configured provider to *fill in a JSON plan* - it
  never writes SQL or Python, and its output is validated against the real
  columns before anything runs;
* the rule planner is a small keyword matcher used when no provider is
  configured, so common questions still work without AI.

Validation is the security boundary: any column, aggregation or filter that
does not exist in the dataset is rejected here, before execution.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

from app.ai.base import CompletionRequest, Message
from app.ai.registry import get_provider
from app.core.config import settings
from app.core.exceptions import AppError, ValidationError
from app.core.logging import get_logger
from app.schemas.analytics import MetricType, TimePeriod
from app.schemas.nlq import (
    DEFAULT_RESULT_ROWS,
    MAX_RESULT_ROWS,
    PlanMeasure,
    PlannerOutput,
    QueryContextTurn,
    QueryIntent,
    QueryPlan,
)
from app.schemas.profiling import DetectedType
from app.services.dataset_query import NUMERIC_TYPES
from app.services.semantic_columns import SemanticModel

logger = get_logger(__name__)

#: Metrics that only make sense over a numeric column.
NUMERIC_AGGREGATIONS = frozenset(
    {MetricType.SUM, MetricType.AVERAGE, MetricType.MEDIAN, MetricType.RANGE, MetricType.STD_DEV}
)

PLANNER_SYSTEM_PROMPT = """You translate a business question into a JSON query plan.

You never write SQL, Python or any code. You only fill in the JSON structure below,
choosing from the columns that actually exist in the dataset.

Respond with JSON only:
{
  "intent": "metric|group|rank|timeseries|comparison|multi_metric",
  "measures": [{"aggregation": "count|distinct_count|sum|average|median|min|max",
                "column": "<column or null for count>", "alias": null}],
  "dimensions": ["<column>"],
  "date_column": "<column or null>",
  "date_period": "day|week|month|quarter|year|null",
  "filters": [{"column": "<column>", "operator":
      "equals|not_equals|contains|greater_than|less_than|greater_or_equal|less_or_equal|between|is_null|is_not_null",
      "value": <value or null>, "value_to": <value or null>}],
  "filter_logic": "and|or",
  "sort_by": "<measure alias or column, or null>",
  "sort_desc": true,
  "limit": 50,
  "chart_type": "bar|line|area|pie|donut|scatter|histogram|box|null",
  "clarification_needed": false,
  "clarification_question": null,
  "candidate_columns": []
}

Rules:
1. Use ONLY column names from the provided list. Never invent one.
2. sum/average/median require a numeric column.
3. If the question needs a column you cannot identify confidently, set
   clarification_needed=true, ask a short question, and list the columns you
   were choosing between in candidate_columns.
4. Use intent "timeseries" only when a date column is involved.
5. Keep limit <= 500.
"""


def build_planner_context(
    frame: pd.DataFrame,
    model: SemanticModel,
    context: list[QueryContextTurn],
) -> dict[str, Any]:
    """Compact dataset description for the planner. Never the raw rows."""
    columns = []
    for role in model.columns:
        entry: dict[str, Any] = {
            "name": role.name,
            "type": role.dtype,
            "usable_as": [
                kind
                for kind, flag in (
                    ("measure", role.measure),
                    ("dimension", role.categorical),
                    ("identifier", role.identifier),
                    ("date", role.temporal),
                )
                if flag
            ],
        }
        # A few example values help the planner build correct filters.
        if role.categorical:
            values = frame[role.name].dropna().astype(str).value_counts().head(8)
            entry["example_values"] = [str(index) for index in values.index]
        columns.append(entry)

    return {
        "columns": columns,
        "business_roles": model.roles,
        "row_count": int(len(frame)),
        "previous_turns": [
            {
                "question": turn.question,
                "plan": turn.plan.model_dump(mode="json") if turn.plan else None,
            }
            for turn in context
        ],
    }


# --- Validation --------------------------------------------------------------


def _resolve_column(frame: pd.DataFrame, name: str) -> str:
    """Map a planner-supplied name onto a real column, case-insensitively."""
    if name in frame.columns:
        return name
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    resolved = lowered.get(name.strip().lower())
    if resolved is None:
        raise ValidationError(f"The dataset has no column called '{name}'.")
    return resolved


def validate_plan(frame: pd.DataFrame, plan: QueryPlan) -> QueryPlan:
    """Check a plan against the dataset before it is executed.

    This is what makes an LLM-authored plan safe: every column is resolved
    against the real frame and every aggregation is checked against the
    column's type. Anything unrecognised is rejected.
    """
    measures: list[PlanMeasure] = []
    for measure in plan.measures:
        if measure.column is None:
            if measure.aggregation is not MetricType.COUNT:
                raise ValidationError(
                    f"'{measure.aggregation.value}' needs a column to work on."
                )
            measures.append(measure)
            continue

        column = _resolve_column(frame, measure.column)
        if measure.aggregation in NUMERIC_AGGREGATIONS:
            from app.services.dataset_profiling import detect_type

            if detect_type(frame[column]) not in NUMERIC_TYPES:
                raise ValidationError(
                    f"'{measure.aggregation.value}' needs a numeric column, but "
                    f"'{column}' is not numeric."
                )
        measures.append(measure.model_copy(update={"column": column}))

    dimensions = [_resolve_column(frame, dimension) for dimension in plan.dimensions]

    date_column = None
    if plan.date_column:
        from app.services.dataset_profiling import detect_type

        date_column = _resolve_column(frame, plan.date_column)
        if detect_type(frame[date_column]) is not DetectedType.DATETIME:
            raise ValidationError(f"'{date_column}' does not contain recognisable dates.")

    filters = [
        item.model_copy(update={"column": _resolve_column(frame, item.column)})
        for item in plan.filters
    ]

    if plan.intent is QueryIntent.TIMESERIES and date_column is None:
        raise ValidationError("A time-based question needs a date column.")
    grouping_intents = (QueryIntent.GROUP, QueryIntent.RANK, QueryIntent.COMPARISON)
    if plan.intent in grouping_intents and not dimensions:
        raise ValidationError("This question needs a column to group by.")
    if not measures:
        # Every intent needs something to measure; default to counting rows.
        measures = [PlanMeasure(aggregation=MetricType.COUNT)]

    return plan.model_copy(
        update={
            "measures": measures,
            "dimensions": dimensions,
            "date_column": date_column,
            "filters": filters,
            "limit": max(1, min(plan.limit, MAX_RESULT_ROWS)),
        }
    )


# --- AI planner --------------------------------------------------------------


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in the planner response.")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Planner response was not an object.")
    return parsed


async def plan_with_ai(
    frame: pd.DataFrame,
    model: SemanticModel,
    question: str,
    context: list[QueryContextTurn],
) -> tuple[PlannerOutput | None, str]:
    """Ask the provider for a plan. Returns (output, status); never raises."""
    try:
        provider = get_provider()
    except AppError as exc:
        return None, f"AI provider unavailable: {exc.message}"

    if not provider.is_configured():
        return None, (
            f"The '{provider.name}' AI provider is not configured; "
            "falling back to keyword interpretation."
        )

    payload = {
        "question": question,
        "dataset": build_planner_context(frame, model, context),
    }
    request = CompletionRequest(
        messages=[Message(role="user", content=json.dumps(payload, default=str))],
        system=PLANNER_SYSTEM_PROMPT,
        max_tokens=900,
        temperature=0.0,
    )

    try:
        import asyncio

        response = await asyncio.wait_for(
            provider.complete(request), timeout=settings.AI_REQUEST_TIMEOUT
        )
    except TimeoutError:
        return None, "The AI provider timed out; falling back to keyword interpretation."
    except AppError as exc:
        return None, f"The AI provider failed: {exc.message}"
    except Exception:
        logger.exception("Unexpected planner failure")
        return None, "The AI provider failed; falling back to keyword interpretation."

    try:
        parsed = _extract_json(response.content)
    except (ValueError, json.JSONDecodeError):
        return None, "The AI plan could not be read; falling back to keyword interpretation."

    if parsed.get("clarification_needed"):
        return (
            PlannerOutput(
                clarification_needed=True,
                clarification_question=str(
                    parsed.get("clarification_question") or "Which column should I use?"
                ),
                candidate_columns=[str(item) for item in parsed.get("candidate_columns", [])][:8],
                source="ai",
            ),
            "ok",
        )

    try:
        plan = QueryPlan.model_validate(parsed)
    except Exception:
        return None, "The AI plan was not valid; falling back to keyword interpretation."

    return PlannerOutput(plan=plan, source="ai"), "ok"


# --- Rule-based planner ------------------------------------------------------

_TOP_N = re.compile(r"\btop\s+(\d{1,3})\b", re.I)
_BOTTOM_N = re.compile(r"\b(bottom|lowest|worst)\s+(\d{1,3})\b", re.I)

_PERIOD_WORDS: dict[str, TimePeriod] = {
    "daily": TimePeriod.DAY,
    "per day": TimePeriod.DAY,
    "weekly": TimePeriod.WEEK,
    "monthly": TimePeriod.MONTH,
    "per month": TimePeriod.MONTH,
    "quarterly": TimePeriod.QUARTER,
    "yearly": TimePeriod.YEAR,
    "annual": TimePeriod.YEAR,
    "per year": TimePeriod.YEAR,
    "over time": TimePeriod.MONTH,
    "trend": TimePeriod.MONTH,
}

_AGGREGATION_WORDS: list[tuple[str, MetricType]] = [
    ("average", MetricType.AVERAGE),
    ("avg", MetricType.AVERAGE),
    ("mean", MetricType.AVERAGE),
    ("median", MetricType.MEDIAN),
    ("maximum", MetricType.MAX),
    ("highest value", MetricType.MAX),
    ("minimum", MetricType.MIN),
    ("how many", MetricType.COUNT),
    ("number of", MetricType.COUNT),
    ("count of", MetricType.COUNT),
    ("unique", MetricType.DISTINCT_COUNT),
    ("distinct", MetricType.DISTINCT_COUNT),
    ("total", MetricType.SUM),
    ("sum", MetricType.SUM),
]


def _match_column(question: str, candidates: list[str]) -> str | None:
    """Longest matching column name mentioned in the question."""
    lowered = question.lower()
    matches = [name for name in candidates if name.lower().replace("_", " ") in lowered]
    matches += [name for name in candidates if name.lower() in lowered]
    if not matches:
        return None
    return max(set(matches), key=len)


def plan_with_rules(
    frame: pd.DataFrame,
    model: SemanticModel,
    question: str,
) -> PlannerOutput:
    """A small deterministic planner, used when no AI provider is available.

    It covers the common shapes (totals, breakdowns, rankings, trends) and asks
    for clarification rather than guessing when the measure is unclear.
    """
    lowered = question.lower().strip()
    measure_names = [column.name for column in model.measures]
    dimension_names = [column.name for column in model.dimensions]

    aggregation = next(
        (metric for word, metric in _AGGREGATION_WORDS if word in lowered), MetricType.SUM
    )

    measure_column = _match_column(question, measure_names) or model.get("revenue")
    dimension = _match_column(question, dimension_names)
    period = next((value for word, value in _PERIOD_WORDS.items() if word in lowered), None)
    date_column = model.get("date") if period else None

    counting = aggregation in (MetricType.COUNT, MetricType.DISTINCT_COUNT)
    if not counting and measure_column is None:
        return PlannerOutput(
            clarification_needed=True,
            clarification_question=(
                "I could not tell which column holds the value you want measured. "
                "Which one should I use?"
            ),
            candidate_columns=measure_names[:8],
            source="rules",
        )

    wants_distinct = "unique" in lowered or "distinct" in lowered
    if counting and measure_column is not None and not wants_distinct:
        # "how many orders" counts rows, not a numeric column.
        measure_column = None

    measures = [
        PlanMeasure(
            aggregation=aggregation,
            column=(
                None
                if aggregation is MetricType.COUNT and measure_column is None
                else measure_column
            ),
        )
    ]

    top_match = _TOP_N.search(lowered)
    bottom_match = _BOTTOM_N.search(lowered)

    if period and date_column:
        intent = QueryIntent.TIMESERIES
        limit = 200
    elif dimension and (top_match or bottom_match or "top" in lowered or "best" in lowered):
        intent = QueryIntent.RANK
        if top_match:
            limit = int(top_match.group(1))
        elif bottom_match:
            limit = int(bottom_match.group(2))
        else:
            limit = 5
    elif dimension:
        intent = QueryIntent.GROUP
        limit = DEFAULT_RESULT_ROWS
    else:
        intent = QueryIntent.METRIC
        limit = 1

    plan = QueryPlan(
        intent=intent,
        measures=measures,
        dimensions=[dimension] if dimension and intent is not QueryIntent.TIMESERIES else [],
        date_column=date_column,
        date_period=period,
        sort_desc=not bool(bottom_match) and "lowest" not in lowered and "worst" not in lowered,
        limit=limit,
    )
    return PlannerOutput(
        plan=plan,
        source="rules",
        notes="Interpreted with keyword rules because no AI provider is configured.",
    )
