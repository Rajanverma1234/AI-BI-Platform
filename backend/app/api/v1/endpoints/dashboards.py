"""Dashboard endpoints.

Two routers, matching the shape the rest of the platform already uses.
Creation and listing are project-scoped and authorise through the project's
owning workspace; everything else is addressed by dashboard id and is scoped to
the owning user, so a dashboard from another workspace is simply not found.

Widget configurations are validated as a discriminated union before any service
sees them, so a widget can never carry a payload its type does not accept.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.pagination import PageParams
from app.core.rate_limit import HeavyRateLimit
from app.models.dashboard import Dashboard
from app.models.report import ReportFileFormat
from app.schemas.common import ErrorResponse
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardData,
    DashboardDetail,
    DashboardDuplicate,
    DashboardFilterOptions,
    DashboardListResponse,
    DashboardRefreshRequest,
    DashboardResponse,
    DashboardTemplateList,
    DashboardUpdate,
    WidgetCreate,
    WidgetResponse,
    WidgetUpdate,
)
from app.schemas.report import ReportResponse
from app.services import dashboard_report, dashboard_service

router = APIRouter(prefix="/projects/{project_id}/dashboards", tags=["dashboards"])
#: Routes addressed by dashboard id, as described in the API design.
dashboard_router = APIRouter(prefix="/dashboards", tags=["dashboards"])

_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project, dataset, dashboard or widget not found"},
    422: {"model": ErrorResponse, "description": "Invalid dashboard or widget configuration"},
}

VersionQuery = Query(default=None, description="Use a cleaned version instead.")
FormatQuery = Query(default=ReportFileFormat.PDF, description="Output format")


def _detail(
    dashboard: Dashboard, dataset_name: str, version_label: str
) -> DashboardDetail:
    """Assemble the full response, including the version the data came from."""
    return DashboardDetail(
        dashboard=DashboardResponse.model_validate(dashboard).model_copy(
            update={"widget_count": len(dashboard.widgets)}
        ),
        dataset_name=dataset_name,
        version_label=version_label,
        widgets=[dashboard_service.to_widget_response(item) for item in dashboard.widgets],
    )


# --- Project-scoped ----------------------------------------------------------


@router.get(
    "/templates",
    response_model=DashboardTemplateList,
    summary="Starter templates and widgets this dataset supports",
    responses=_RESPONSES,
)
async def dashboard_templates(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    version_id: uuid.UUID | None = VersionQuery,
) -> DashboardTemplateList:
    """Each template is reduced to the widgets this dataset can actually fill."""
    return await dashboard_service.templates_for_dataset(
        session, storage, current_user, project_id, dataset_id, version_id
    )


@router.post(
    "",
    response_model=DashboardDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dashboard",
    responses=_RESPONSES,
)
async def create_dashboard(
    project_id: uuid.UUID,
    payload: DashboardCreate,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> DashboardDetail:
    """Optionally seeded from a template, adapted to the dataset's own columns."""
    dashboard = await dashboard_service.create_dashboard(
        session, storage, current_user, project_id, payload
    )
    loaded = await dashboard_service.load_source(session, storage, current_user, dashboard)
    return _detail(dashboard, loaded.dataset.name, dashboard_service.version_label(loaded))


@router.get(
    "",
    response_model=DashboardListResponse,
    summary="List dashboards in a project",
    responses=_RESPONSES,
)
async def list_dashboards(
    project_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    pagination: PageParams,
) -> DashboardListResponse:
    dashboards, total, counts = await dashboard_service.list_dashboards(
        session, current_user, project_id, pagination
    )
    return DashboardListResponse.build(
        items=[
            DashboardResponse.model_validate(item).model_copy(
                update={"widget_count": counts.get(item.id, 0)}
            )
            for item in dashboards
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


# --- Dashboard-scoped --------------------------------------------------------


@dashboard_router.get(
    "/{dashboard_id}",
    response_model=DashboardDetail,
    summary="Get a dashboard and its widgets",
    responses=_RESPONSES,
)
async def get_dashboard(
    dashboard_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> DashboardDetail:
    dashboard = await dashboard_service.get_dashboard(session, current_user, dashboard_id)
    loaded = await dashboard_service.load_source(session, storage, current_user, dashboard)
    return _detail(dashboard, loaded.dataset.name, dashboard_service.version_label(loaded))


@dashboard_router.patch(
    "/{dashboard_id}",
    response_model=DashboardDetail,
    summary="Rename, refilter, relayout or move a dashboard to another version",
    responses=_RESPONSES,
)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardUpdate,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> DashboardDetail:
    """Changing the dataset version is explicit; it never happens implicitly."""
    dashboard = await dashboard_service.update_dashboard(
        session, storage, current_user, dashboard_id, payload
    )
    loaded = await dashboard_service.load_source(session, storage, current_user, dashboard)
    return _detail(dashboard, loaded.dataset.name, dashboard_service.version_label(loaded))


@dashboard_router.post(
    "/{dashboard_id}/duplicate",
    response_model=DashboardDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate a dashboard and its widgets",
    responses=_RESPONSES,
)
async def duplicate_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardDuplicate,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> DashboardDetail:
    copy = await dashboard_service.duplicate_dashboard(
        session, current_user, dashboard_id, payload
    )
    loaded = await dashboard_service.load_source(session, storage, current_user, copy)
    return _detail(copy, loaded.dataset.name, dashboard_service.version_label(loaded))


@dashboard_router.delete(
    "/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dashboard and its widgets",
    responses=_RESPONSES,
)
async def delete_dashboard(
    dashboard_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> None:
    await dashboard_service.delete_dashboard(session, current_user, dashboard_id)


@dashboard_router.get(
    "/{dashboard_id}/filters",
    response_model=DashboardFilterOptions,
    summary="Filterable fields, taken from the dataset's own columns",
    responses=_RESPONSES,
)
async def dashboard_filters(
    dashboard_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> DashboardFilterOptions:
    return await dashboard_service.filter_options(session, storage, current_user, dashboard_id)


@dashboard_router.post(
    "/{dashboard_id}/refresh",
    response_model=DashboardData,
    summary="Resolve every widget against the pinned dataset version",
    dependencies=[HeavyRateLimit],
    responses=_RESPONSES,
)
async def refresh_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardRefreshRequest,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> DashboardData:
    """A widget that fails carries its own error; the rest still resolve.

    `filters` layers ad-hoc conditions over the saved ones without changing
    them, which is how cross-widget filtering works; `widget_ids` narrows the
    refresh to a single widget.
    """
    return await dashboard_service.refresh(
        session, storage, current_user, dashboard_id, payload
    )


@dashboard_router.post(
    "/{dashboard_id}/export",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Export a dashboard through the existing report engine",
    dependencies=[HeavyRateLimit],
    responses={
        **_RESPONSES,
        503: {"model": ErrorResponse, "description": "Storage unavailable"},
    },
)
async def export_dashboard(
    dashboard_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    file_format: ReportFileFormat = FormatQuery,
) -> ReportResponse:
    """Produces an ordinary report, downloaded through the reports routes."""
    report = await dashboard_report.export(
        session, storage, current_user, dashboard_id, file_format
    )
    return ReportResponse.model_validate(report)


# --- Widgets -----------------------------------------------------------------


@dashboard_router.post(
    "/{dashboard_id}/widgets",
    response_model=WidgetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a widget",
    responses=_RESPONSES,
)
async def add_widget(
    dashboard_id: uuid.UUID,
    payload: WidgetCreate,
    session: DbSession,
    current_user: CurrentUser,
) -> WidgetResponse:
    widget = await dashboard_service.add_widget(session, current_user, dashboard_id, payload)
    return dashboard_service.to_widget_response(widget)


@dashboard_router.patch(
    "/{dashboard_id}/widgets/{widget_id}",
    response_model=WidgetResponse,
    summary="Update a widget's title, position or configuration",
    responses=_RESPONSES,
)
async def update_widget(
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
    session: DbSession,
    current_user: CurrentUser,
) -> WidgetResponse:
    widget = await dashboard_service.update_widget(
        session, current_user, dashboard_id, widget_id, payload
    )
    return dashboard_service.to_widget_response(widget)


@dashboard_router.delete(
    "/{dashboard_id}/widgets/{widget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a widget",
    responses=_RESPONSES,
)
async def delete_widget(
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> None:
    await dashboard_service.delete_widget(session, current_user, dashboard_id, widget_id)
