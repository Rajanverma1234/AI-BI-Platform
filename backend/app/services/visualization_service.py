"""Orchestration for preview, query, charts and EDA.

Each function authorises and loads once through ``dataset_access``, then hands
the frame to a deterministic computation service. Routes stay thin.
"""

from __future__ import annotations

import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Pagination
from app.models.user import User
from app.schemas.visualization import (
    ChartConfig,
    ChartDataResponse,
    ChartSuggestionsResponse,
    CorrelationResponse,
    DataPreviewResponse,
    EdaSummaryResponse,
    PreviewColumn,
    QueryRequest,
    QueryResponse,
)
from app.services import dataset_access, dataset_charts, dataset_eda, dataset_query
from app.services.dataset_profiling import detect_type
from app.storage.base import StorageProvider


async def preview(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    pagination: Pagination,
    version_id: uuid.UUID | None = None,
) -> DataPreviewResponse:
    """Return one page of rows. The full dataset never leaves the backend."""
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    frame = loaded.frame

    total_rows = int(len(frame))
    total_pages = math.ceil(total_rows / pagination.page_size) if total_rows else 0
    window = frame.iloc[pagination.offset : pagination.offset + pagination.limit]

    return DataPreviewResponse(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        columns=[
            PreviewColumn(name=str(name), dtype=detect_type(frame[name]))
            for name in frame.columns
        ],
        rows=dataset_query.rows_to_records(window),
        total_rows=total_rows,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=total_pages,
        has_next=pagination.page < total_pages,
        has_previous=pagination.page > 1 and total_rows > 0,
    )


async def run_query(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: QueryRequest,
) -> QueryResponse:
    """Filter, optionally aggregate, and return a bounded result set."""
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, request.version_id
    )

    filtered = dataset_query.apply_filters(loaded.frame, request.filters)
    total_matched = int(len(filtered))

    if request.aggregations:
        result = dataset_query.aggregate(filtered, request.group_by, request.aggregations)
    else:
        selected = request.columns or [str(name) for name in filtered.columns]
        for column in selected:
            dataset_query.require_column(filtered, column)
        result = filtered[selected]

    if request.sort_by:
        dataset_query.require_column(result, request.sort_by)
        result = result.sort_values(request.sort_by, ascending=not request.sort_desc)

    truncated = len(result) > request.limit
    result = result.head(request.limit)

    return QueryResponse(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        columns=[str(name) for name in result.columns],
        rows=dataset_query.rows_to_records(result),
        row_count=int(len(result)),
        total_matched=total_matched,
        truncated=truncated,
    )


async def build_chart(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    config: ChartConfig,
) -> ChartDataResponse:
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, config.version_id
    )
    return dataset_charts.build_chart(loaded.frame, config)


async def eda_summary(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> EdaSummaryResponse:
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    return dataset_eda.build_summary(
        loaded.frame, dataset_id=loaded.dataset.id, version_id=loaded.version_id
    )


async def correlation(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    method: str = "pearson",
) -> CorrelationResponse:
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    return dataset_eda.build_correlation(
        loaded.frame,
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        method=method,
    )


async def chart_suggestions(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> ChartSuggestionsResponse:
    """Rule-based suggestions derived from detected column types."""
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    suggestions = dataset_charts.suggest_charts(loaded.frame)

    # Echo the source back on each config so the UI can run it unchanged.
    for suggestion in suggestions:
        suggestion.config.version_id = loaded.version_id

    return ChartSuggestionsResponse(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        suggestions=suggestions,
    )
