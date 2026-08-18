"""Behaviour when no AI provider is configured.

The platform ships with `AI_PROVIDER=null` and must be fully usable that way.
Every AI-backed feature has a deterministic fallback, and the contract is that
the fallback is *honest*: it says AI was unavailable rather than presenting a
stub's output as a model's answer.

Regression for a bug where `NullProvider.is_configured()` returned True. Every
call site branches on that check, so the fallbacks were all skipped and the
stub's echo was served to users - most visibly as an NLQ "answer" containing
"[null-provider] no AI provider configured; received: {...}" plus an echoed
dump of the internal context.
"""

from __future__ import annotations

import uuid

import pandas as pd
import pytest

from app.ai.registry import build_provider, get_provider
from app.models.dataset import Dataset, DatasetFileType, DatasetStatus
from app.schemas.nlq import NlqRequest
from app.services import (
    ai_analyst_service,
    data_quality,
    dataset_access,
    dataset_profiling,
    insights_service,
    nlq_executor,
    nlq_planner,
    nlq_service,
    semantic_columns,
)

ROWS = 200


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": range(1, ROWS + 1),
            "customer_id": [2000 + (i % 40) for i in range(ROWS)],
            "region": ["North" if i % 2 else "South" for i in range(ROWS)],
            "total_amount": [round(10.0 + (i % 50) * 1.5, 2) for i in range(ROWS)],
            "order_date": pd.date_range("2024-01-01", periods=ROWS, freq="D"),
        }
    )


@pytest.fixture
def loaded(frame: pd.DataFrame) -> dataset_access.LoadedDataset:
    dataset = Dataset(
        id=uuid.uuid4(),
        name="Sales",
        original_filename="sales.csv",
        storage_key="datasets/test/data.csv",
        file_type=DatasetFileType.CSV,
        file_size=1,
        status=DatasetStatus.READY,
        project_id=uuid.uuid4(),
    )
    return dataset_access.LoadedDataset(dataset=dataset, frame=frame, version=None)


def analyst_report(frame: pd.DataFrame, loaded: dataset_access.LoadedDataset):
    profile = dataset_profiling.profile_frame(frame, dataset_id=loaded.dataset.id)
    quality = data_quality.assess_quality(profile, frame, dataset_id=loaded.dataset.id)
    return ai_analyst_service.build_report(frame, loaded, profile=profile, quality=quality)


# --- The provider contract ---------------------------------------------------


def test_the_default_provider_reports_no_ai_available() -> None:
    assert build_provider("null").is_configured() is False
    assert get_provider().is_configured() is False


# --- Analyst -----------------------------------------------------------------


async def test_the_analyst_says_ai_is_unavailable_rather_than_faking_success(
    frame: pd.DataFrame, loaded: dataset_access.LoadedDataset
) -> None:
    report = analyst_report(frame, loaded)

    narrative, status = await ai_analyst_service.interpret(report)

    assert narrative is None
    assert "not configured" in status
    # The bug produced an empty narrative object with status "ok".
    assert status != "ok"


async def test_a_follow_up_question_is_declined_clearly(
    frame: pd.DataFrame, loaded: dataset_access.LoadedDataset
) -> None:
    report = analyst_report(frame, loaded)
    context = ai_analyst_service.build_context(report)

    assert context, "the deterministic context is still built"

    narrative, status = await ai_analyst_service.interpret(report)
    assert narrative is None and status


# --- Insights ----------------------------------------------------------------


async def test_insights_report_ai_as_unavailable(
    frame: pd.DataFrame, loaded: dataset_access.LoadedDataset
) -> None:
    analyst = analyst_report(frame, loaded)
    report = insights_service.build_deterministic(
        frame,
        loaded,
        analyst,
        data_quality.assess_quality(
            dataset_profiling.profile_frame(frame, dataset_id=loaded.dataset.id),
            frame,
            dataset_id=loaded.dataset.id,
        ),
        project_id=loaded.dataset.project_id,
        generated_by="Tester",
    )

    narrative, status, extra = await insights_service.interpret(report)

    assert narrative is None
    assert extra == []
    # This is the exact wording the Insights page shows the user.
    assert "unavailable" in status.lower()
    assert "data-driven insights" in status.lower()


async def test_deterministic_insights_are_still_produced(
    frame: pd.DataFrame, loaded: dataset_access.LoadedDataset
) -> None:
    """The point of degrading gracefully: the feature still works."""
    analyst = analyst_report(frame, loaded)
    quality = data_quality.assess_quality(
        dataset_profiling.profile_frame(frame, dataset_id=loaded.dataset.id),
        frame,
        dataset_id=loaded.dataset.id,
    )
    report = insights_service.build_deterministic(
        frame, loaded, analyst, quality,
        project_id=loaded.dataset.project_id, generated_by="Tester",
    )

    assert report.insights
    assert report.summary.strip()
    assert all(item.evidence for item in report.insights)


# --- NLQ ---------------------------------------------------------------------


async def test_nlq_answers_deterministically_without_stub_text(
    frame: pd.DataFrame,
) -> None:
    """The user-visible half of the regression.

    With the stub claiming to be configured, this returned the provider's echo
    - "[null-provider] ... received: {json}" - straight to the user.
    """
    model = semantic_columns.detect(frame)
    output = nlq_planner.plan_with_rules(frame, model, "What is total total_amount?")
    assert output.plan is not None

    plan = nlq_planner.validate_plan(frame, output.plan)
    result = nlq_executor.execute(frame, plan)
    deterministic = nlq_executor.describe_answer("What is total total_amount?", plan, result)

    answer, ai_available, status, flagged = await nlq_service._phrase_answer(
        "What is total total_amount?", result, deterministic
    )

    assert answer == deterministic
    assert ai_available is False
    assert flagged is False
    assert "null-provider" not in answer
    assert "received:" not in answer
    assert status and "not configured" in status


async def test_the_nlq_planner_falls_back_to_rules(frame: pd.DataFrame) -> None:
    model = semantic_columns.detect(frame)

    output, status = await nlq_planner.plan_with_ai(frame, model, "total total_amount", [])

    # No AI plan, and the caller is told why so it can use the rule planner.
    assert output is None
    assert status


def test_the_request_model_still_validates(frame: pd.DataFrame) -> None:
    assert NlqRequest(question="What is total total_amount?").question
