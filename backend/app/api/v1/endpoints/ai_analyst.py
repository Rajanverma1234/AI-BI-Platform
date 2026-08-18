"""AI analyst endpoints.

Routes stay thin: authorization runs through the shared dependency and
``dataset_access``; the pipeline lives in ``ai_analyst_service``. Deterministic
analysis is always returned even when the AI provider is unavailable.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, Storage
from app.core.rate_limit import AiRateLimit
from app.schemas.ai_analyst import (
    AnalystAnswerResponse,
    AnalystQuestionRequest,
    AnalystReport,
    AnalyzeRequest,
)
from app.schemas.common import ErrorResponse
from app.services import ai_analyst_service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}/ai-analyst",
    tags=["ai-analyst"],
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset or version not accessible"},
    422: {"model": ErrorResponse, "description": "Dataset not ready, empty, or unanalysable"},
}


@router.post(
    "/analyze",
    response_model=AnalystReport,
    summary="Analyse a dataset and generate insights",
    dependencies=[AiRateLimit],
    responses=_RESPONSES,
)
async def analyze(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: AnalyzeRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> AnalystReport:
    """Deterministic insights first, then optional AI interpretation.

    If the AI provider is missing, misconfigured, slow or failing, the report
    is still returned with `ai_available: false` and a reason in `ai_status`.
    """
    return await ai_analyst_service.analyze(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.post(
    "/ask",
    response_model=AnalystAnswerResponse,
    summary="Ask a follow-up question about the analysis",
    dependencies=[AiRateLimit],
    responses=_RESPONSES,
)
async def ask(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: AnalystQuestionRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> AnalystAnswerResponse:
    """Answers from the same analytical context the report was built from.

    This is not a natural-language query engine: no query is generated or run
    against the data.
    """
    return await ai_analyst_service.answer_question(
        session,
        storage,
        current_user,
        project_id,
        dataset_id,
        payload.version_id,
        payload.question,
    )
