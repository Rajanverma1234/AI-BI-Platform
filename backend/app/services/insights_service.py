"""AI insights orchestration.

The pipeline the prompt describes, in order:

    dataset_access.load_for_user      one authorisation gate, one file read
    -> profiling + quality            existing services, computed once
    -> ai_analyst_service.build_report existing KPIs, trends, anomalies, segments
    -> customer analytics             RFM + churn, run once, shared
    -> business_insight_engine        deterministic detection + prioritisation
    -> business_health                transparent score
    -> AI interpretation              optional, additive, never load-bearing
    -> InsightRun                     persisted so history is reconstructible

Two boundaries matter. The deterministic half is the source of truth: it runs
to completion whether or not a provider is configured, and every number in the
report comes from it. The AI half only reads the compact context it is handed -
never raw rows - and anything it writes that cannot be traced back to that
context is flagged rather than silently trusted.

This complements the AI Data Analyst rather than replacing it: that module
answers questions the user asks, this one surfaces findings the user did not
know to ask about. Both share the same analyst context and the same
number-verification helper.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import CompletionRequest, Message
from app.ai.registry import get_provider
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.models.insight_run import InsightRun
from app.models.user import User
from app.schemas.ai_analyst import AnalystReport
from app.schemas.insights import (
    AiInsightNarrative,
    BusinessInsight,
    GenerateInsightsRequest,
    InsightCategory,
    InsightFilters,
    InsightPriority,
    InsightReport,
    InsightSeverity,
    Recommendation,
    RunStatus,
    build_context_payload,
)
from app.schemas.profiling import DataQualitySummary
from app.services import (
    ai_analyst_service,
    business_health,
    data_quality,
    dataset_access,
    dataset_profiling,
    semantic_columns,
)
from app.services import business_insight_engine as detector
from app.storage.base import StorageProvider

logger = get_logger(__name__)

RUN_NOT_FOUND = "Insight run not found."

ANALYSIS_VERSION = detector.ANALYSIS_VERSION

SYSTEM_PROMPT = (
    "You are a business analyst briefing a business owner. You will receive a "
    "JSON context of already-computed findings about their data: a business "
    "health score with its factors, deterministic insights with the evidence "
    "behind them, and candidate recommendations.\n"
    "Rules you must follow:\n"
    "1. Use ONLY the numbers present in the context. Never estimate, "
    "extrapolate or invent a figure, a percentage, a customer count, a date or "
    "a ranking.\n"
    "2. If something is not in the context, say it is not available.\n"
    "3. Describe outliers as potential anomalies needing review, never as "
    "confirmed errors. Describe correlations as associations, never as proven "
    "causes.\n"
    "4. Never promise a financial outcome. Say 'potential impact', not "
    "'will increase revenue'.\n"
    "5. Explain why the findings matter and which deserve attention first. Do "
    "not simply restate them.\n"
    "6. Be concise and write for a business owner, not an analyst.\n"
    "Respond with JSON only, in this exact shape:\n"
    '{"headline": "...", "interpretation": ["..."], "priorities": ["..."], '
    '"recommendations": [{"title": "...", "action": "...", "reason": "...", '
    '"expected_impact": "..."}]}'
)


# --- Pipeline ----------------------------------------------------------------


def build_deterministic(
    frame: pd.DataFrame,
    loaded: dataset_access.LoadedDataset,
    analyst: AnalystReport,
    quality: DataQualitySummary,
    *,
    project_id: uuid.UUID,
    generated_by: str,
) -> InsightReport:
    """The deterministic half of the pipeline, on an already-loaded frame.

    Pure and synchronous. Taking the analyst report and quality summary as
    arguments is what lets reporting reuse this without profiling the same
    frame a second time.
    """
    model = semantic_columns.detect(frame)

    # RFM and churn are the expensive steps; run once, share with the score.
    customers = detector.build_customer_analytics(frame, model)

    insights, skipped, rfm_segments = detector.detect_all(
        frame, model, analyst, quality, customers
    )
    health = business_health.evaluate(frame, model, analyst, customers)

    return InsightReport(
        project_id=project_id,
        dataset_id=loaded.dataset.id,
        dataset_name=loaded.dataset.name,
        version_id=loaded.version_id,
        version_label=(
            f"v{loaded.version.version_number} - {loaded.version.name}"
            if loaded.version
            else "Original dataset"
        ),
        analysis_version=ANALYSIS_VERSION,
        generated_at=datetime.now(UTC),
        generated_by=generated_by,
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
        summary=detector.summarise(frame, insights, health.score),
        health=health,
        insights=insights,
        recommendations=detector.build_recommendations(insights),
        supporting_metrics=detector.supporting_metrics(analyst)
        + business_health.health_evidence(health),
        filters=_filters(frame, model, insights, rfm_segments),
        counts_by_category=_count(insights, lambda item: item.category.value),
        counts_by_severity=_count(insights, lambda item: item.severity.value),
        counts_by_priority=_count(insights, lambda item: item.priority.value),
        skipped=skipped,
    )


async def _build_report(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    *,
    version_id: uuid.UUID | None,
    include_ai: bool,
) -> InsightReport:
    """Load, analyse and optionally interpret. The page's entry point."""
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    frame = loaded.frame

    profile = dataset_profiling.profile_frame(
        frame, dataset_id=loaded.dataset.id, version_id=loaded.version_id
    )
    quality = data_quality.assess_quality(
        profile, frame, dataset_id=loaded.dataset.id, version_id=loaded.version_id
    )
    # Raises a readable ValidationError when the dataset has no rows.
    analyst = ai_analyst_service.build_report(frame, loaded, profile=profile, quality=quality)

    report = build_deterministic(
        frame,
        loaded,
        analyst,
        quality,
        project_id=project_id,
        generated_by=user.display_name or user.email,
    )

    if include_ai:
        narrative, status, extra = await interpret(report)
        report.ai = narrative
        report.ai_available = narrative is not None
        report.ai_status = status
        # AI recommendations are appended, never substituted: the deterministic
        # plan stands on its own if the provider is unavailable.
        report.recommendations = [*report.recommendations, *extra]
    else:
        report.ai_status = "AI interpretation was not requested."

    return report


def _count(
    insights: list[BusinessInsight], key: Callable[[BusinessInsight], str]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for insight in insights:
        value = key(insight)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _filters(
    frame: pd.DataFrame,
    model: semantic_columns.SemanticModel,
    insights: list[BusinessInsight],
    rfm_segments: list[str],
) -> InsightFilters:
    """Filter options built from this dataset and this run - never hard-coded."""
    product = model.get("product")
    region = model.get("region")

    # Only offer the enum values that actually occur in this run's findings.
    present_categories = {item.category for item in insights}
    present_severities = {item.severity for item in insights}
    present_priorities = {item.priority for item in insights}

    return InsightFilters(
        categories=[item for item in InsightCategory if item in present_categories],
        severities=[item for item in InsightSeverity if item in present_severities],
        priorities=[item for item in InsightPriority if item in present_priorities],
        products=detector.distinct_values(frame, product),
        regions=detector.distinct_values(frame, region),
        customer_segments=sorted(set(rfm_segments)),
        periods=detector.period_labels(frame, model),
        product_column=product,
        region_column=region,
        date_column=model.get("date"),
    )


# --- AI layer ----------------------------------------------------------------


async def interpret(
    report: InsightReport,
) -> tuple[AiInsightNarrative | None, str, list[Recommendation]]:
    """Ask the configured provider to interpret the evidence.

    Never raises: a provider failure must not cost the user the deterministic
    report. Returns (narrative, status, extra recommendations).
    """
    try:
        provider = get_provider()
    except AppError as exc:
        return None, f"AI provider unavailable: {exc.message}", []

    if not provider.is_configured():
        return None, (
            f"AI interpretation unavailable: the '{provider.name}' provider is not "
            "configured. Showing data-driven insights."
        ), []

    context = build_context_payload(report)
    request = CompletionRequest(
        messages=[Message(role="user", content=json.dumps(context, default=str))],
        system=SYSTEM_PROMPT,
        max_tokens=2000,
        temperature=0.0,
    )

    try:
        response = await asyncio.wait_for(
            provider.complete(request), timeout=settings.AI_REQUEST_TIMEOUT
        )
    except TimeoutError:
        return None, "The AI provider timed out. Showing data-driven insights.", []
    except AppError as exc:
        return None, f"The AI provider failed: {exc.message}", []
    except Exception:
        logger.exception("Unexpected AI provider failure generating insights")
        return None, "The AI provider failed. Showing data-driven insights.", []

    try:
        parsed = ai_analyst_service._parse_ai_json(response.content)
    except (ValueError, json.JSONDecodeError):
        logger.info("AI insight response was not valid JSON")
        return None, "The AI response could not be read. Showing data-driven insights.", []

    headline = str(parsed.get("headline", "")).strip() or None
    interpretation = [
        str(item) for item in parsed.get("interpretation", []) if str(item).strip()
    ]
    priorities = [str(item) for item in parsed.get("priorities", []) if str(item).strip()]

    extra: list[Recommendation] = []
    for index, item in enumerate(parsed.get("recommendations", [])):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        action = str(item.get("action", "")).strip()
        if not title or not action:
            continue
        extra.append(
            Recommendation(
                id=f"rec-ai-{index}",
                title=title,
                action=action,
                reason=str(item.get("reason", "")).strip()
                or "Derived from the findings on this page.",
                # The AI reads every insight, so it cannot be attributed to one.
                supporting_insight_ids=[],
                expected_impact=str(item.get("expected_impact", "")).strip()
                or "Potential impact: an improvement in this area.",
                priority=InsightPriority.MEDIUM,
                source=provider.name,
            )
        )

    # The same number-safety net the AI Data Analyst uses, on the same context.
    combined = " ".join(
        filter(
            None,
            [
                headline,
                *interpretation,
                *priorities,
                *[f"{item.title} {item.action} {item.reason}" for item in extra],
            ],
        )
    )
    untraceable = ai_analyst_service.find_untraceable_numbers(combined, context)

    return (
        AiInsightNarrative(
            headline=headline,
            interpretation=interpretation[:10],
            priorities=priorities[:10],
            provider=response.provider,
            model=response.model,
            contains_untraceable_numbers=bool(untraceable),
            untraceable_values=untraceable[:10],
        ),
        "ok",
        extra[:5],
    )


# --- Persistence -------------------------------------------------------------


def _record(
    user: User,
    project_id: uuid.UUID,
    report: InsightReport,
) -> InsightRun:
    return InsightRun(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project_id,
        dataset_id=report.dataset_id,
        dataset_version_id=report.version_id,
        analysis_version=report.analysis_version,
        status=RunStatus.READY,
        health_score=report.health.score,
        health_rating=report.health.rating.value,
        insight_count=len(report.insights),
        recommendation_count=len(report.recommendations),
        ai_available=report.ai_available,
        ai_status=(report.ai_status or "")[:500] or None,
        result=report.model_dump(mode="json"),
    )


async def generate(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: GenerateInsightsRequest,
) -> tuple[InsightReport, InsightRun | None]:
    """Generate insights and, unless asked not to, record the run."""
    report = await _build_report(
        session,
        storage,
        user,
        project_id,
        dataset_id,
        version_id=request.version_id,
        include_ai=request.include_ai,
    )

    if not request.persist:
        return report, None

    run = _record(user, project_id, report)
    session.add(run)
    await session.flush()

    report.run_id = run.id
    # Store the id inside the payload too, so a fetched run is self-describing.
    run.result = report.model_dump(mode="json")
    return report, run


async def refresh(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    run_id: uuid.UUID,
    include_ai: bool = True,
) -> tuple[InsightReport, InsightRun]:
    """Re-run the analysis for an existing run's dataset and version.

    A new run is recorded rather than the old one being overwritten, so the
    history keeps what was true at each point in time.
    """
    previous = await get_run(session, user, run_id)
    report = await _build_report(
        session,
        storage,
        user,
        previous.project_id,
        previous.dataset_id,
        version_id=previous.dataset_version_id,
        include_ai=include_ai,
    )

    run = _record(user, previous.project_id, report)
    session.add(run)
    await session.flush()
    report.run_id = run.id
    run.result = report.model_dump(mode="json")
    return report, run


async def list_runs(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    pagination: Pagination,
) -> tuple[list[InsightRun], int]:
    """This user's insight runs for this dataset, newest first."""
    # Authorises the dataset before any run row is exposed.
    await dataset_access.load_for_user(session, storage, user, project_id, dataset_id, None)

    mine = (InsightRun.dataset_id == dataset_id) & (InsightRun.user_id == user.id)
    total = await session.scalar(select(func.count()).select_from(InsightRun).where(mine)) or 0
    result = await session.execute(
        select(InsightRun)
        .where(mine)
        .order_by(desc(InsightRun.created_at))
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    return list(result.scalars().all()), total


async def get_run(session: AsyncSession, user: User, run_id: uuid.UUID) -> InsightRun:
    """Load one run, scoped to the caller.

    Scoping by user is what keeps this route safe without a project in the
    path: a guessed id belonging to another tenant simply is not found.
    """
    result = await session.execute(
        select(InsightRun).where(InsightRun.id == run_id, InsightRun.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise NotFoundError(RUN_NOT_FOUND)
    return run


async def latest_run(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> InsightRun | None:
    """The most recent run for this dataset, if there is one."""
    await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    result = await session.execute(
        select(InsightRun)
        .where(
            InsightRun.dataset_id == dataset_id,
            InsightRun.user_id == user.id,
            InsightRun.status == RunStatus.READY,
        )
        .order_by(desc(InsightRun.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


def stored_report(
    run: InsightRun,
    *,
    viewing_version: uuid.UUID | None = None,
    compare_version: bool = False,
) -> InsightReport | None:
    """Rehydrate a stored run, marking it stale when it no longer applies.

    A run is stale when the detection rules have moved on since it was written,
    or when the user is looking at a different dataset version than the one it
    analysed. Either way it is still shown - just never presented as current.
    """
    if run.result is None:
        return None

    try:
        report = InsightReport.model_validate(run.result)
    except ValueError:
        logger.warning("Stored insight run %s could not be read back", run.id)
        return None

    report.run_id = run.id
    stale = run.analysis_version != ANALYSIS_VERSION
    if compare_version:
        stale = stale or run.dataset_version_id != viewing_version
    report.stale = stale
    return report
