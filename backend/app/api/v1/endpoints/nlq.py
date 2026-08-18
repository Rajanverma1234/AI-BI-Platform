"""Natural-language query endpoints.

Mounted at /nlq rather than /query: the dataset visualisation module already
owns POST .../query for structured queries, and two handlers on one path would
silently shadow each other.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.pagination import PageParams
from app.core.rate_limit import AiRateLimit
from app.schemas.common import ErrorResponse, Page
from app.schemas.nlq import (
    NlqRequest,
    NlqResponse,
    QueryHistoryEntry,
    QuerySuggestionsResponse,
)
from app.services import nlq_service

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}/nlq",
    tags=["nlq"],
)

QueryHistoryResponse = Page[QueryHistoryEntry]

VersionQuery = Query(
    default=None,
    description="Use a cleaned version instead of the original upload.",
)

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset or version not accessible"},
    422: {"model": ErrorResponse, "description": "Dataset not ready, empty, or question invalid"},
}


@router.post(
    "",
    response_model=NlqResponse,
    summary="Ask a question about the dataset in natural language",
    dependencies=[AiRateLimit],
    responses=_RESPONSES,
)
async def ask(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: NlqRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> NlqResponse:
    """Plan, validate, execute, then word the answer.

    The AI only produces a query plan; the plan is validated against the real
    columns and executed deterministically. Every figure in the answer comes
    from that execution.
    """
    return await nlq_service.ask(
        session, storage, current_user, project_id, dataset_id, payload
    )


@router.get(
    "/history",
    response_model=QueryHistoryResponse,
    summary="Recent questions asked about this dataset",
    responses=_RESPONSES,
)
async def history(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    pagination: PageParams,
) -> QueryHistoryResponse:
    """Scoped to the calling user; never exposes another user's questions."""
    entries, total = await nlq_service.history(
        session, storage, current_user, project_id, dataset_id, pagination
    )
    return QueryHistoryResponse.build(
        items=[QueryHistoryEntry.model_validate(entry) for entry in entries],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/suggestions",
    response_model=QuerySuggestionsResponse,
    summary="Suggested questions for this dataset",
    responses=_RESPONSES,
)
async def suggestions(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> QuerySuggestionsResponse:
    """Derived deterministically from the dataset's columns - no AI call."""
    return await nlq_service.suggestions(
        session, storage, current_user, project_id, dataset_id, version_id
    )
