"""AI analyst orchestration.

Pipeline: authorise and load once -> deterministic profiling, KPIs, trends,
anomalies, segments and quality -> optional AI interpretation -> structured
report.

The deterministic layer is the source of truth. The AI layer only interprets
the compact context it is given; the raw dataset is never sent. Every number
the AI writes is checked against the figures it received, and anything it
cannot be traced to is reported rather than silently trusted.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import CompletionRequest, Message
from app.ai.registry import get_provider
from app.core.config import settings
from app.core.exceptions import AppError, ValidationError
from app.core.logging import get_logger
from app.models.user import User
from app.schemas.ai_analyst import (
    AiNarrative,
    AnalystAnswerResponse,
    AnalystReport,
    AnalyzeRequest,
    Insight,
    InsightCategory,
    InsightSeverity,
    TrendDirection,
    TrendFinding,
)
from app.schemas.profiling import DataQualitySummary, DatasetProfile
from app.services import (
    data_quality,
    dataset_access,
    dataset_profiling,
    insight_engine,
    semantic_columns,
)
from app.storage.base import StorageProvider

logger = get_logger(__name__)

#: Bump when the analysis pipeline changes, so cached reports are not reused.
ANALYSIS_VERSION = "1"
#: Cached reports live this long; a dataset version is immutable, so this is
#: really just a memory bound rather than a correctness concern.
CACHE_TTL_SECONDS = 900
CACHE_MAX_ENTRIES = 64

#: In-process cache. Deliberately not a database table: reports are derived
#: data and cheap to rebuild, so persisting them would add a migration and a
#: staleness problem for no real gain.
_CACHE: dict[str, tuple[float, AnalystReport]] = {}


def _cache_key(
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None,
    updated_at: datetime,
    include_ai: bool,
) -> str:
    # updated_at is part of the key so replacing a dataset file invalidates it.
    return "|".join(
        [
            str(dataset_id),
            str(version_id or "original"),
            updated_at.isoformat(),
            ANALYSIS_VERSION,
            "ai" if include_ai else "deterministic",
        ]
    )


def _cache_get(key: str) -> AnalystReport | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    stored_at, report = entry
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return report


def _cache_put(key: str, report: AnalystReport) -> None:
    if len(_CACHE) >= CACHE_MAX_ENTRIES:
        oldest = min(_CACHE, key=lambda item: _CACHE[item][0])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (time.monotonic(), report)


# --- Deterministic summary ---------------------------------------------------


def _deterministic_summary(
    frame: pd.DataFrame,
    insights: list[Insight],
    trends: list[TrendFinding],
) -> str:
    """A readable summary that does not depend on any AI provider."""
    parts = [f"The dataset holds {len(frame):,} rows across {len(frame.columns)} columns."]

    kpi = next((item for item in insights if item.category is InsightCategory.KPI), None)
    if kpi and kpi.value is not None:
        parts.append(f"{kpi.title} is {kpi.value:,.2f}.")

    moving = [
        trend
        for trend in trends
        if trend.direction in (TrendDirection.INCREASING, TrendDirection.DECREASING)
    ]
    if moving:
        trend = moving[0]
        parts.append(
            f"{trend.metric_column} is {trend.direction.value} "
            f"({trend.percentage_change:+.1f}% from {trend.first_label} to {trend.last_label})."
        )

    high = [item for item in insights if item.severity is InsightSeverity.HIGH]
    if high:
        parts.append(f"Most pressing: {high[0].summary}")

    return " ".join(parts)


def _recommendations(insights: list[Insight]) -> list[str]:
    """Only recommendations tied to a detected finding; no generic advice."""
    severity_rank = {
        InsightSeverity.HIGH: 0,
        InsightSeverity.MEDIUM: 1,
        InsightSeverity.LOW: 2,
        InsightSeverity.INFO: 3,
    }
    ranked = sorted(insights, key=lambda item: severity_rank[item.severity])
    seen: set[str] = set()
    output: list[str] = []
    for insight in ranked:
        if not insight.recommendation or insight.recommendation in seen:
            continue
        seen.add(insight.recommendation)
        output.append(insight.recommendation)
        if len(output) >= 8:
            break
    return output


# --- AI layer ----------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a business data analyst. You will receive a JSON context of "
    "already-computed statistics about a dataset.\n"
    "Rules you must follow:\n"
    "1. Use ONLY the numbers present in the context. Never estimate, "
    "extrapolate or invent a figure.\n"
    "2. If something is not in the context, say it is not available.\n"
    "3. Describe outliers as potential anomalies needing review, never as "
    "confirmed errors.\n"
    "4. Describe correlations as associations, never as proven causes.\n"
    "5. Be concise and business-oriented.\n"
    "Respond with JSON only, in this exact shape:\n"
    '{"executive_summary": "...", "key_findings": ["..."], '
    '"recommendations": ["..."]}'
)

#: Matches numbers in AI output so they can be checked against the context.
_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")


def build_context(report: AnalystReport) -> dict[str, Any]:
    """The compact analytical context sent to the AI. Never the raw rows."""
    return {
        "dataset": {
            "name": report.dataset_name,
            "rows": report.row_count,
            "columns": report.column_count,
            "version": report.version_label,
        },
        "semantic_columns": [item.model_dump() for item in report.semantic_columns],
        "kpis": [
            {"name": kpi.name, "value": kpi.value, "column": kpi.column}
            for kpi in report.kpis
            if kpi.available
        ],
        "trends": [trend.model_dump(mode="json") for trend in report.trends],
        "anomalies": [anomaly.model_dump(mode="json") for anomaly in report.anomalies],
        "segments": [segment.model_dump(mode="json") for segment in report.segments],
        "insights": [
            {
                "id": insight.id,
                "category": insight.category.value,
                "title": insight.title,
                "summary": insight.summary,
                "value": insight.value,
                "severity": insight.severity.value,
            }
            for insight in report.insights
        ],
        "data_quality": [note.model_dump() for note in report.data_quality],
    }


def _collect_numbers(payload: Any, into: set[str]) -> None:
    """Every numeric value in the context, in a few printable forms."""
    if isinstance(payload, dict):
        for value in payload.values():
            _collect_numbers(value, into)
    elif isinstance(payload, list):
        for value in payload:
            _collect_numbers(value, into)
    elif isinstance(payload, bool):
        return
    elif isinstance(payload, (int, float)):
        number = float(payload)
        if math.isnan(number) or math.isinf(number):
            return
        into.add(f"{number:.0f}")
        into.add(f"{number:.1f}")
        into.add(f"{number:.2f}")
        into.add(f"{abs(number):.0f}")
        into.add(f"{abs(number):.1f}")
        into.add(f"{abs(number):.2f}")
    elif isinstance(payload, str):
        for match in _NUMBER_PATTERN.findall(payload):
            cleaned = match.replace(",", "")
            try:
                number = float(cleaned)
            except ValueError:
                continue
            into.add(f"{number:.0f}")
            into.add(f"{number:.1f}")
            into.add(f"{number:.2f}")


def find_untraceable_numbers(text: str, context: dict[str, Any]) -> list[str]:
    """Numbers in the AI text that do not appear in the supplied context.

    A safety net for the "never invent numbers" rule: years and small counts
    are ignored to avoid flagging ordinary prose.
    """
    allowed: set[str] = set()
    _collect_numbers(context, allowed)

    untraceable: list[str] = []
    for match in _NUMBER_PATTERN.findall(text):
        cleaned = match.replace(",", "")
        try:
            number = float(cleaned)
        except ValueError:
            continue
        # Ignore list numbering and other incidental small integers.
        if abs(number) < 10 and number == int(number):
            continue
        if any(f"{number:.{digits}f}" in allowed for digits in (0, 1, 2)):
            continue
        untraceable.append(match)

    return sorted(set(untraceable))


def _parse_ai_json(content: str) -> dict[str, Any]:
    """Extract the JSON object from the model's reply."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in the response.")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Response was not a JSON object.")
    return parsed


async def interpret(report: AnalystReport) -> tuple[AiNarrative | None, str]:
    """Ask the configured provider to interpret the context.

    Returns (narrative, status). A failure never raises: the deterministic
    report must still be delivered.
    """
    try:
        provider = get_provider()
    except AppError as exc:
        return None, f"AI provider unavailable: {exc.message}"

    if not provider.is_configured():
        return None, (
            f"The '{provider.name}' AI provider is not configured, so only "
            "deterministic analysis is shown."
        )

    context = build_context(report)
    request = CompletionRequest(
        messages=[
            Message(role="user", content=json.dumps(context, default=str)),
        ],
        system=SYSTEM_PROMPT,
        max_tokens=1500,
        temperature=0.0,
    )

    try:
        response = await asyncio.wait_for(
            provider.complete(request), timeout=settings.AI_REQUEST_TIMEOUT
        )
    except TimeoutError:
        return None, "The AI provider timed out; deterministic analysis is shown."
    except AppError as exc:
        return None, f"The AI provider failed: {exc.message}"
    except Exception:
        logger.exception("Unexpected AI provider failure")
        return None, "The AI provider failed; deterministic analysis is shown."

    try:
        parsed = _parse_ai_json(response.content)
    except (ValueError, json.JSONDecodeError):
        logger.info("AI response was not valid JSON")
        return None, "The AI response could not be read; deterministic analysis is shown."

    findings = [str(item) for item in parsed.get("key_findings", []) if str(item).strip()]
    recommendations = [
        str(item) for item in parsed.get("recommendations", []) if str(item).strip()
    ]
    summary = str(parsed.get("executive_summary", "")).strip() or None

    combined = " ".join(filter(None, [summary, *findings, *recommendations]))
    untraceable = find_untraceable_numbers(combined, context)

    return (
        AiNarrative(
            executive_summary=summary,
            key_findings=findings[:10],
            recommendations=recommendations[:10],
            provider=response.provider,
            model=response.model,
            contains_untraceable_numbers=bool(untraceable),
            untraceable_values=untraceable[:10],
        ),
        "ok",
    )


# --- Report ------------------------------------------------------------------


def build_report(
    frame: pd.DataFrame,
    loaded: dataset_access.LoadedDataset,
    *,
    profile: DatasetProfile | None = None,
    quality: DataQualitySummary | None = None,
) -> AnalystReport:
    """The deterministic half of the pipeline. No AI involved.

    ``profile`` and ``quality`` may be supplied by a caller that already
    computed them (reporting does), so the same frame is never profiled twice.
    """
    if frame.empty:
        raise ValidationError("This dataset has no rows to analyse.")

    model = semantic_columns.detect(frame)

    if profile is None:
        profile = dataset_profiling.profile_frame(
            frame, dataset_id=loaded.dataset.id, version_id=loaded.version_id
        )
    if quality is None:
        quality = data_quality.assess_quality(
            profile, frame, dataset_id=loaded.dataset.id, version_id=loaded.version_id
        )

    kpis = insight_engine.build_kpis(frame, model)
    trends = insight_engine.build_trends(frame, model)
    anomalies = insight_engine.build_anomalies(frame, model)
    segments = insight_engine.build_segments(frame, model)
    notes, quality_insights = insight_engine.quality_notes(quality)

    insights = [
        *insight_engine.kpi_insights(kpis, model),
        *insight_engine.trend_insights(trends),
        *insight_engine.anomaly_insights(anomalies),
        *insight_engine.segment_insights(segments),
        *insight_engine.relationship_insights(frame, model),
        *quality_insights,
    ]

    return AnalystReport(
        dataset_id=loaded.dataset.id,
        dataset_name=loaded.dataset.name,
        version_id=loaded.version_id,
        version_label=(
            f"v{loaded.version.version_number} — {loaded.version.name}"
            if loaded.version
            else "Original dataset"
        ),
        generated_at=datetime.now(UTC),
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
        summary=_deterministic_summary(frame, insights, trends),
        semantic_columns=model.as_schema(),
        kpis=kpis,
        insights=insights,
        trends=trends,
        anomalies=anomalies,
        segments=segments,
        recommendations=_recommendations(insights),
        data_quality=notes,
    )


async def analyze(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: AnalyzeRequest,
) -> AnalystReport:
    """Full pipeline, with caching keyed on the exact source analysed."""
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, request.version_id
    )

    key = _cache_key(
        loaded.dataset.id, loaded.version_id, loaded.dataset.updated_at, request.include_ai
    )
    if not request.refresh:
        cached = _cache_get(key)
        if cached is not None:
            return cached.model_copy(update={"cached": True})

    report = build_report(loaded.frame, loaded)

    if request.include_ai:
        narrative, status = await interpret(report)
        report.ai = narrative
        report.ai_available = narrative is not None
        report.ai_status = status
    else:
        report.ai_status = "AI interpretation was not requested."

    _cache_put(key, report)
    return report


# --- Follow-up questions -----------------------------------------------------

QUESTION_SYSTEM_PROMPT = (
    "You are a business data analyst answering a question about a dataset. "
    "You will receive a JSON context of already-computed statistics.\n"
    "Rules:\n"
    "1. Answer ONLY from the context. Never invent or estimate a number.\n"
    "2. If the context does not contain the answer, say so plainly and name "
    "what would be needed.\n"
    "3. Describe outliers as potential anomalies and correlations as "
    "associations.\n"
    "4. Answer in at most 150 words, in plain business language."
)


async def answer_question(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None,
    question: str,
) -> AnalystAnswerResponse:
    """Answer a follow-up question from the analytical context.

    This is deliberately not a natural-language query engine: no query is
    generated or executed. The model only reads the same context the report
    was built from.
    """
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )

    key = _cache_key(loaded.dataset.id, loaded.version_id, loaded.dataset.updated_at, True)
    report = _cache_get(key) or build_report(loaded.frame, loaded)
    context = build_context(report)

    try:
        provider = get_provider()
    except AppError as exc:
        return AnalystAnswerResponse(
            question=question,
            answer=(
                "The AI provider is unavailable, so this question cannot be answered. "
                "The deterministic insights on this page still apply."
            ),
            ai_available=False,
            ai_status=exc.message,
        )

    if not provider.is_configured():
        return AnalystAnswerResponse(
            question=question,
            answer=(
                f"The '{provider.name}' AI provider is not configured, so follow-up "
                "questions are unavailable. The insights below were computed "
                "without AI and still apply."
            ),
            ai_available=False,
            ai_status="provider not configured",
        )

    request = CompletionRequest(
        messages=[
            Message(
                role="user",
                content=json.dumps({"question": question, "context": context}, default=str),
            )
        ],
        system=QUESTION_SYSTEM_PROMPT,
        max_tokens=600,
        temperature=0.0,
    )

    try:
        response = await asyncio.wait_for(
            provider.complete(request), timeout=settings.AI_REQUEST_TIMEOUT
        )
    except TimeoutError:
        return AnalystAnswerResponse(
            question=question,
            answer="The AI provider timed out. Please try again.",
            ai_available=False,
            ai_status="timeout",
        )
    except AppError as exc:
        return AnalystAnswerResponse(
            question=question,
            answer="The AI provider could not answer this question.",
            ai_available=False,
            ai_status=exc.message,
        )
    except Exception:
        logger.exception("Unexpected AI provider failure answering a question")
        return AnalystAnswerResponse(
            question=question,
            answer="The AI provider could not answer this question.",
            ai_available=False,
            ai_status="provider error",
        )

    untraceable = find_untraceable_numbers(response.content, context)

    return AnalystAnswerResponse(
        question=question,
        answer=response.content.strip(),
        ai_available=True,
        ai_status="ok",
        supporting_insight_ids=[insight.id for insight in report.insights[:10]],
        contains_untraceable_numbers=bool(untraceable),
    )
