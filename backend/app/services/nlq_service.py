"""Natural-language query orchestration.

Pipeline: authorise and load -> plan (AI, else rules) -> validate against real
columns -> deterministic execution -> optional AI wording -> record history.

The model never touches the data. It only produces a plan, and that plan is
validated before the executor runs it.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import CompletionRequest, Message
from app.ai.registry import get_provider
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.models.nlq_query import NlqQuery
from app.models.user import User
from app.schemas.analytics import MetricType
from app.schemas.nlq import (
    NlqRequest,
    NlqResponse,
    QueryPlan,
    QueryResult,
    QueryStatus,
    QuerySuggestion,
    QuerySuggestionsResponse,
)
from app.services import dataset_access, nlq_executor, nlq_planner, semantic_columns
from app.storage.base import StorageProvider

logger = get_logger(__name__)

ANSWER_SYSTEM_PROMPT = (
    "You turn a computed query result into one or two sentences of business "
    "English.\n"
    "Rules:\n"
    "1. Use ONLY the numbers in the result. Never invent, round differently or "
    "estimate a figure.\n"
    "2. Do not add analysis the result does not support.\n"
    "3. Be direct and concise. No preamble, no bullet points.\n"
    "Reply with plain text only."
)

_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")


def _result_numbers(result: QueryResult) -> set[str]:
    """Every number in the result, in a few printable forms."""
    allowed: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        number = float(value)
        for digits in (0, 1, 2):
            allowed.add(f"{number:.{digits}f}")
            allowed.add(f"{abs(number):.{digits}f}")

    for row in result.rows:
        for value in row.values():
            add(value)
    add(result.metric_value)
    add(result.row_count)
    return allowed


def _untraceable(text: str, result: QueryResult) -> bool:
    """True when the wording contains a figure the result does not support."""
    allowed = _result_numbers(result)
    for match in _NUMBER_PATTERN.findall(text):
        cleaned = match.replace(",", "")
        try:
            number = float(cleaned)
        except ValueError:
            continue
        # Small whole numbers are ordinary prose ("top 5", "3 regions").
        if abs(number) < 10 and number == int(number):
            continue
        if not any(f"{number:.{digits}f}" in allowed for digits in (0, 1, 2)):
            return True
    return False


async def _phrase_answer(
    question: str, result: QueryResult, fallback: str
) -> tuple[str, bool, str | None, bool]:
    """Ask the provider to word the answer. Returns (answer, ai, status, flagged)."""
    try:
        provider = get_provider()
    except AppError as exc:
        return fallback, False, exc.message, False

    if not provider.is_configured():
        return fallback, False, "AI provider not configured; showing the computed answer.", False

    payload = {
        "question": question,
        "result": {
            "columns": [column.model_dump() for column in result.columns],
            "rows": result.rows[:50],
            "metric_label": result.metric_label,
            "metric_value": result.metric_value,
            "row_count": result.row_count,
        },
    }
    request = CompletionRequest(
        messages=[Message(role="user", content=json.dumps(payload, default=str))],
        system=ANSWER_SYSTEM_PROMPT,
        max_tokens=300,
        temperature=0.0,
    )

    try:
        response = await asyncio.wait_for(
            provider.complete(request), timeout=settings.AI_REQUEST_TIMEOUT
        )
    except TimeoutError:
        return fallback, False, "The AI provider timed out; showing the computed answer.", False
    except AppError as exc:
        return fallback, False, f"The AI provider failed: {exc.message}", False
    except Exception:
        logger.exception("Unexpected failure phrasing an answer")
        return fallback, False, "The AI provider failed; showing the computed answer.", False

    text = response.content.strip()
    if not text:
        return fallback, False, "The AI returned nothing; showing the computed answer.", False

    if _untraceable(text, result):
        # Prefer the number-safe answer over fluent but unverifiable wording.
        logger.info("Discarded AI wording containing untraceable numbers")
        return fallback, True, "ok", True

    return text, True, "ok", False


async def _record(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None,
    question: str,
    plan: QueryPlan | None,
    status: QueryStatus,
    error_message: str | None = None,
) -> None:
    """Persist the question and plan. Never stores results or credentials."""
    session.add(
        NlqQuery(
            user_id=user.id,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            question=question[:500],
            plan=plan.model_dump(mode="json") if plan else None,
            status=status.value,
            error_message=error_message[:500] if error_message else None,
        )
    )
    await session.flush()


async def ask(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: NlqRequest,
) -> NlqResponse:
    """Answer a natural-language question about the dataset."""
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, request.version_id
    )
    frame = loaded.frame
    model = semantic_columns.detect(frame)

    base = {
        "question": request.question,
        "dataset_id": loaded.dataset.id,
        "version_id": loaded.version_id,
        "generated_at": datetime.now(UTC),
    }

    if frame.empty:
        await _record(
            session, user, project_id, dataset_id, loaded.version_id,
            request.question, None, QueryStatus.FAILED, "The dataset has no rows.",
        )
        return NlqResponse(
            **base, success=False, answer="This dataset has no rows to query.",
            ai_status="not attempted",
        )

    # 1. Plan - AI first, deterministic rules as the fallback.
    output, ai_status = await nlq_planner.plan_with_ai(
        frame, model, request.question, request.context
    )
    ai_used = output is not None
    if output is None:
        output = nlq_planner.plan_with_rules(frame, model, request.question)

    if output.clarification_needed or output.plan is None:
        question_text = (
            output.clarification_question
            or "I could not tell which column you meant. Which one should I use?"
        )
        await _record(
            session, user, project_id, dataset_id, loaded.version_id,
            request.question, None, QueryStatus.CLARIFICATION, question_text,
        )
        return NlqResponse(
            **base,
            success=False,
            answer=question_text,
            clarification_needed=True,
            clarification_question=question_text,
            candidate_columns=output.candidate_columns,
            ai_available=ai_used,
            ai_status=ai_status if not ai_used else "ok",
            plan_source=output.source,
        )

    # 2. Validate the plan against the real dataset, then execute it.
    try:
        plan = nlq_planner.validate_plan(frame, output.plan)
        result = nlq_executor.execute(frame, plan)
    except AppError as exc:
        await _record(
            session, user, project_id, dataset_id, loaded.version_id,
            request.question, output.plan, QueryStatus.FAILED, exc.message,
        )
        return NlqResponse(
            **base,
            success=False,
            answer=exc.message,
            plan=output.plan,
            ai_available=ai_used,
            ai_status=ai_status if not ai_used else "ok",
            plan_source=output.source,
        )

    # 3. Word the answer; the numbers always come from the executed result.
    deterministic = nlq_executor.describe_answer(request.question, plan, result)
    answer, ai_available, answer_status, flagged = await _phrase_answer(
        request.question, result, deterministic
    )

    await _record(
        session, user, project_id, dataset_id, loaded.version_id,
        request.question, plan, QueryStatus.SUCCESS,
    )

    return NlqResponse(
        **base,
        success=True,
        answer=answer,
        plan=plan,
        result=result,
        calculation=nlq_executor.describe(plan),
        chart=nlq_executor.recommend_chart(plan, result),
        ai_available=ai_available or ai_used,
        ai_status=answer_status if ai_available else (ai_status or answer_status),
        plan_source=output.source,
        contains_untraceable_numbers=flagged,
    )


async def history(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    pagination: Pagination,
) -> tuple[list[NlqQuery], int]:
    """This user's recent questions for this dataset."""
    # Authorises the dataset before any history row is exposed.
    await dataset_access.load_for_user(session, storage, user, project_id, dataset_id, None)

    from sqlalchemy import func

    mine = (NlqQuery.dataset_id == dataset_id) & (NlqQuery.user_id == user.id)
    total = await session.scalar(select(func.count()).select_from(NlqQuery).where(mine)) or 0
    result = await session.execute(
        select(NlqQuery)
        .where(mine)
        .order_by(desc(NlqQuery.created_at))
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    return list(result.scalars().all()), total


def build_suggestions(
    frame: pd.DataFrame,
    model: semantic_columns.SemanticModel,
) -> list[QuerySuggestion]:
    """Deterministic question suggestions from the dataset's own columns.

    No LLM call: these follow directly from which business roles exist.
    """
    suggestions: list[QuerySuggestion] = [
        QuerySuggestion(question="How many records are there?", reason="Always answerable.")
    ]

    revenue = model.get("revenue")
    quantity = model.get("quantity")
    product = model.get("product")
    region = model.get("region")
    channel = model.get("channel")
    rating = model.get("rating")
    date = model.get("date")
    customer = model.get("customer")

    if revenue:
        suggestions.append(
            QuerySuggestion(
                question=f"What is the total {revenue}?",
                reason=f"'{revenue}' is a numeric measure.",
            )
        )
    if revenue and product:
        suggestions.append(
            QuerySuggestion(
                question=f"What are the top 5 {product} by {revenue}?",
                reason=f"'{product}' is a dimension and '{revenue}' is a measure.",
            )
        )
    if revenue and region:
        suggestions.append(
            QuerySuggestion(
                question=f"Which {region} has the highest {revenue}?",
                reason=f"'{region}' is a dimension and '{revenue}' is a measure.",
            )
        )
    if revenue and date:
        suggestions.append(
            QuerySuggestion(
                question=f"Show monthly {revenue}.",
                reason=f"'{date}' is a date column and '{revenue}' is a measure.",
            )
        )
    if quantity and product:
        suggestions.append(
            QuerySuggestion(
                question=f"What is the total {quantity} by {product}?",
                reason=f"'{quantity}' is a measure and '{product}' is a dimension.",
            )
        )
    if channel:
        suggestions.append(
            QuerySuggestion(
                question=f"Which {channel} is used most often?",
                reason=f"'{channel}' is a categorical dimension.",
            )
        )
    if rating:
        suggestions.append(
            QuerySuggestion(
                question=f"What is the average {rating}?",
                reason=f"'{rating}' is a numeric measure.",
            )
        )
    if customer:
        suggestions.append(
            QuerySuggestion(
                question=f"How many unique {customer} are there?",
                reason=f"'{customer}' looks like an identifier.",
            )
        )

    return suggestions[:10]


async def suggestions(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> QuerySuggestionsResponse:
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    model = semantic_columns.detect(loaded.frame)
    return QuerySuggestionsResponse(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        suggestions=build_suggestions(loaded.frame, model),
    )


__all__ = ["ask", "build_suggestions", "history", "suggestions", "MetricType"]
