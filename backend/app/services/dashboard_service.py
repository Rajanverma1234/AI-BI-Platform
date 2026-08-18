"""Dashboard orchestration: authorise, load once, resolve, respond.

This layer owns persistence and sequencing; it owns no analytics. Every figure
on a dashboard is produced by a service that already existed - the dashboard
decides *which* questions to ask and in what order, and ``dashboard_widgets``
adapts each one onto the service that answers it.

The performance contract for a refresh is one pass over the expensive work:

    dataset_access.load_for_user     one authorisation gate, one file read
    -> latest InsightRun             one query, shared by every AI widget
    -> recorded NLQ plans            one query, shared by every NLQ widget
    -> resolve each widget           against the frame already in memory

A dashboard of twenty widgets therefore reads its dataset once, not twenty
times, and never recomputes a metric that another widget already asked for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.models.dashboard import Dashboard, DashboardWidget
from app.models.insight_run import InsightRun
from app.models.nlq_query import NlqQuery
from app.models.user import User
from app.schemas.dashboard import (
    MAX_WIDGETS,
    DashboardCreate,
    DashboardData,
    DashboardDuplicate,
    DashboardFilterOptions,
    DashboardRefreshRequest,
    DashboardTemplateList,
    DashboardUpdate,
    FilterField,
    TemplateWidget,
    WidgetCreate,
    WidgetPosition,
    WidgetResponse,
    WidgetUpdate,
)
from app.schemas.insights import InsightReport, RunStatus
from app.schemas.profiling import DetectedType
from app.schemas.visualization import FilterSet
from app.services import (
    dashboard_templates,
    dashboard_widgets,
    dataset_access,
    dataset_profiling,
    dataset_query,
    dataset_service,
    insights_service,
    semantic_columns,
)
from app.storage.base import StorageProvider

logger = get_logger(__name__)

DASHBOARD_NOT_FOUND = "Dashboard not found."
WIDGET_NOT_FOUND = "Widget not found."

#: Distinct values offered per categorical filter field.
MAX_FILTER_VALUES = 100
#: A column with more distinct values than this is an identifier, not a filter.
MAX_FILTER_CARDINALITY = 200


def version_label(loaded: dataset_access.LoadedDataset) -> str:
    """What the header shows. A dashboard always states the data it uses."""
    if loaded.version is not None:
        return f"v{loaded.version.version_number} - {loaded.version.name}"
    return "Original dataset"


def to_widget_response(widget: DashboardWidget) -> WidgetResponse:
    return WidgetResponse(
        id=widget.id,
        dashboard_id=widget.dashboard_id,
        widget_type=widget.widget_type,
        title=widget.title,
        position=WidgetPosition(
            x=widget.position_x,
            y=widget.position_y,
            width=widget.width,
            height=widget.height,
        ),
        configuration=widget.configuration,
        created_at=widget.created_at,
        updated_at=widget.updated_at,
    )


# --- Authorisation -----------------------------------------------------------


async def get_dashboard(
    session: AsyncSession, user: User, dashboard_id: uuid.UUID
) -> Dashboard:
    """Load a dashboard the caller owns, with its widgets.

    Scoping by ``user_id`` is the gate for the id-addressed routes: a dashboard
    belonging to another workspace simply is not found, so a guessed id reveals
    nothing about whether it exists.
    """
    result = await session.execute(
        select(Dashboard)
        .options(selectinload(Dashboard.widgets))
        .where(Dashboard.id == dashboard_id, Dashboard.user_id == user.id)
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise NotFoundError(DASHBOARD_NOT_FOUND)
    return dashboard


async def load_source(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    dashboard: Dashboard,
) -> dataset_access.LoadedDataset:
    """Re-run the full dataset authorisation for the dashboard's source.

    Owning the dashboard is not enough: the dataset it points at is checked
    again on every read, so revoking access to a dataset revokes the dashboard
    that reads it.
    """
    return await dataset_access.load_for_user(
        session,
        storage,
        user,
        dashboard.project_id,
        dashboard.dataset_id,
        dashboard.dataset_version_id,
    )


# --- CRUD --------------------------------------------------------------------


async def list_dashboards(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    pagination: Pagination,
) -> tuple[list[Dashboard], int, dict[uuid.UUID, int]]:
    """This user's dashboards in a project, newest first, with widget counts."""
    # Authorises the project through its owning workspace.
    await dataset_service.get_project_for_user(session, user, project_id)

    mine = (Dashboard.project_id == project_id) & (Dashboard.user_id == user.id)
    total = await session.scalar(select(func.count()).select_from(Dashboard).where(mine)) or 0
    result = await session.execute(
        select(Dashboard)
        .where(mine)
        .order_by(desc(Dashboard.created_at))
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    dashboards = list(result.scalars().all())

    counts: dict[uuid.UUID, int] = {}
    if dashboards:
        rows = await session.execute(
            select(DashboardWidget.dashboard_id, func.count())
            .where(DashboardWidget.dashboard_id.in_([item.id for item in dashboards]))
            .group_by(DashboardWidget.dashboard_id)
        )
        counts = {row[0]: int(row[1]) for row in rows}

    return dashboards, total, counts


async def create_dashboard(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    payload: DashboardCreate,
) -> Dashboard:
    """Create a dashboard, optionally seeded from a template."""
    # Authorises project -> dataset -> version in one step, and gives us the
    # frame the template needs to decide which widgets are supportable.
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, payload.dataset_id, payload.dataset_version_id
    )

    if payload.template and not dashboard_templates.template_exists(payload.template):
        raise ValidationError(f"Unknown dashboard template '{payload.template}'.")

    dashboard = Dashboard(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project_id,
        dataset_id=loaded.dataset.id,
        dataset_version_id=loaded.version_id,
        name=payload.name,
        description=payload.description,
        layout_columns=payload.layout_columns,
    )
    session.add(dashboard)
    await session.flush()

    if payload.template:
        model = semantic_columns.detect(loaded.frame)
        template = dashboard_templates.build_template(payload.template, model)
        dashboard.layout_columns = template.layout_columns
        for widget in template.widgets:
            session.add(_widget_row(dashboard.id, widget))
        await session.flush()

    # INSERT does not return the server-default timestamps, so load them here
    # rather than letting the response trigger lazy async IO.
    await session.refresh(dashboard, ["widgets", "created_at", "updated_at"])
    return dashboard


def _widget_row(dashboard_id: uuid.UUID, widget: TemplateWidget | WidgetCreate) -> DashboardWidget:
    return DashboardWidget(
        id=uuid.uuid4(),
        dashboard_id=dashboard_id,
        widget_type=widget.configuration.widget_type,
        title=widget.title,
        position_x=widget.position.x,
        position_y=widget.position.y,
        width=widget.position.width,
        height=widget.position.height,
        configuration=widget.configuration.model_dump(mode="json"),
    )


async def update_dashboard(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    dashboard_id: uuid.UUID,
    payload: DashboardUpdate,
) -> Dashboard:
    """Rename, re-filter, relayout, or move to another dataset version."""
    dashboard = await get_dashboard(session, user, dashboard_id)

    if payload.name is not None:
        dashboard.name = payload.name
    if payload.description is not None:
        dashboard.description = payload.description
    if payload.layout_columns is not None:
        dashboard.layout_columns = payload.layout_columns
    if payload.filters is not None:
        dashboard.filters = payload.filters.model_dump(mode="json")

    # Changing version is deliberate and re-authorised; it never happens
    # implicitly just because a newer version exists.
    if payload.clear_version:
        dashboard.dataset_version_id = None
    elif payload.dataset_version_id is not None:
        await dataset_access.load_for_user(
            session,
            storage,
            user,
            dashboard.project_id,
            dashboard.dataset_id,
            payload.dataset_version_id,
        )
        dashboard.dataset_version_id = payload.dataset_version_id

    if payload.layout is not None:
        by_id = {widget.id: widget for widget in dashboard.widgets}
        for item in payload.layout:
            widget = by_id.get(item.widget_id)
            if widget is None:
                raise NotFoundError(WIDGET_NOT_FOUND)
            widget.position_x = item.position.x
            widget.position_y = item.position.y
            widget.width = item.position.width
            widget.height = item.position.height

    await session.flush()
    # UPDATE does not use RETURNING, so the onupdate `updated_at` is expired;
    # refresh explicitly rather than let the response trigger lazy async IO.
    await session.refresh(dashboard, ["widgets", "updated_at"])
    return dashboard


async def duplicate_dashboard(
    session: AsyncSession,
    user: User,
    dashboard_id: uuid.UUID,
    payload: DashboardDuplicate,
) -> Dashboard:
    """Copy a dashboard and every widget, keeping the same dataset version."""
    source = await get_dashboard(session, user, dashboard_id)

    copy = Dashboard(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=source.project_id,
        dataset_id=source.dataset_id,
        dataset_version_id=source.dataset_version_id,
        name=(payload.name or f"{source.name} (copy)")[:200],
        description=source.description,
        layout_columns=source.layout_columns,
        filters=source.filters,
    )
    session.add(copy)
    await session.flush()

    for widget in source.widgets:
        session.add(
            DashboardWidget(
                id=uuid.uuid4(),
                dashboard_id=copy.id,
                widget_type=widget.widget_type,
                title=widget.title,
                position_x=widget.position_x,
                position_y=widget.position_y,
                width=widget.width,
                height=widget.height,
                configuration=widget.configuration,
            )
        )
    await session.flush()
    await session.refresh(copy, ["widgets", "created_at", "updated_at"])
    return copy


async def delete_dashboard(
    session: AsyncSession, user: User, dashboard_id: uuid.UUID
) -> None:
    dashboard = await get_dashboard(session, user, dashboard_id)
    await session.delete(dashboard)
    await session.flush()


# --- Widgets -----------------------------------------------------------------


async def add_widget(
    session: AsyncSession, user: User, dashboard_id: uuid.UUID, payload: WidgetCreate
) -> DashboardWidget:
    dashboard = await get_dashboard(session, user, dashboard_id)
    if len(dashboard.widgets) >= MAX_WIDGETS:
        raise ValidationError(
            f"A dashboard can hold at most {MAX_WIDGETS} widgets. Remove one first."
        )
    if payload.position.width > dashboard.layout_columns:
        raise ValidationError(
            f"A widget cannot be wider than the dashboard's {dashboard.layout_columns} columns."
        )

    widget = _widget_row(dashboard.id, payload)
    session.add(widget)
    await session.flush()
    await session.refresh(widget, ["created_at", "updated_at"])
    return widget


async def get_widget(
    session: AsyncSession, user: User, dashboard_id: uuid.UUID, widget_id: uuid.UUID
) -> DashboardWidget:
    dashboard = await get_dashboard(session, user, dashboard_id)
    widget = next((item for item in dashboard.widgets if item.id == widget_id), None)
    if widget is None:
        raise NotFoundError(WIDGET_NOT_FOUND)
    return widget


async def update_widget(
    session: AsyncSession,
    user: User,
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
) -> DashboardWidget:
    widget = await get_widget(session, user, dashboard_id, widget_id)

    if payload.title is not None:
        widget.title = payload.title
    if payload.position is not None:
        widget.position_x = payload.position.x
        widget.position_y = payload.position.y
        widget.width = payload.position.width
        widget.height = payload.position.height
    if payload.configuration is not None:
        # Replaced wholesale: a widget cannot change type mid-update and end up
        # with a configuration that does not match it.
        widget.widget_type = payload.configuration.widget_type
        widget.configuration = payload.configuration.model_dump(mode="json")

    await session.flush()
    await session.refresh(widget, ["updated_at"])
    return widget


async def delete_widget(
    session: AsyncSession, user: User, dashboard_id: uuid.UUID, widget_id: uuid.UUID
) -> None:
    widget = await get_widget(session, user, dashboard_id, widget_id)
    await session.delete(widget)
    await session.flush()


# --- Refresh -----------------------------------------------------------------


async def _insight_context(
    session: AsyncSession, user: User, dashboard: Dashboard
) -> tuple[InsightReport | None, uuid.UUID | None, datetime | None, bool]:
    """The latest insight run for this dashboard's dataset, fetched once."""
    result = await session.execute(
        select(InsightRun)
        .where(
            InsightRun.dataset_id == dashboard.dataset_id,
            InsightRun.user_id == user.id,
            InsightRun.status == RunStatus.READY,
        )
        .order_by(desc(InsightRun.created_at))
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return None, None, None, False

    report = insights_service.stored_report(
        run, viewing_version=dashboard.dataset_version_id, compare_version=True
    )
    if report is None:
        return None, None, None, False
    return report, run.id, run.created_at, report.stale


async def _nlq_plans(
    session: AsyncSession, user: User, widgets: list[DashboardWidget]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Recorded query plans for every NLQ widget, in one query."""
    wanted: list[uuid.UUID] = []
    for widget in widgets:
        configuration = widget.configuration or {}
        raw = configuration.get("nlq_query_id")
        if raw:
            try:
                wanted.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
    if not wanted:
        return {}

    result = await session.execute(
        # Scoped by user: a widget cannot replay another tenant's saved query.
        select(NlqQuery).where(NlqQuery.id.in_(wanted), NlqQuery.user_id == user.id)
    )
    return {
        row.id: {"question": row.question, "plan": row.plan} for row in result.scalars().all()
    }


async def refresh(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    dashboard_id: uuid.UUID,
    request: DashboardRefreshRequest | None = None,
) -> DashboardData:
    """Resolve every widget against the dashboard's pinned dataset version."""
    request = request or DashboardRefreshRequest()
    dashboard = await get_dashboard(session, user, dashboard_id)
    loaded = await load_source(session, storage, user, dashboard)

    saved = FilterSet.model_validate(dashboard.filters) if dashboard.filters else None
    # Ad-hoc filters from a chart click layer on top of the saved ones.
    applied = dashboard_widgets.merge_filters(saved, request.filters)

    insights, run_id, generated_at, stale = await _insight_context(session, user, dashboard)

    widgets = list(dashboard.widgets)
    if request.widget_ids is not None:
        wanted = set(request.widget_ids)
        widgets = [widget for widget in widgets if widget.id in wanted]

    context = dashboard_widgets.WidgetContext(
        frame=loaded.frame,
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        dashboard_filters=applied,
        insights=insights,
        insight_run_id=run_id,
        insight_generated_at=generated_at,
        insight_stale=stale,
        nlq_plans=await _nlq_plans(session, user, widgets),
    )

    filtered = dataset_query.apply_filters(loaded.frame, applied)

    return DashboardData(
        dashboard_id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        dataset_id=loaded.dataset.id,
        dataset_name=loaded.dataset.name,
        version_id=loaded.version_id,
        version_label=version_label(loaded),
        layout_columns=dashboard.layout_columns,
        row_count=int(len(loaded.frame)),
        refreshed_at=datetime.now(UTC),
        applied_filters=applied.model_dump(mode="json") if applied else None,
        filtered_row_count=int(len(filtered)),
        widgets=[dashboard_widgets.resolve(widget, context) for widget in widgets],
    )


# --- Filters and templates ---------------------------------------------------


async def filter_options(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    dashboard_id: uuid.UUID,
) -> DashboardFilterOptions:
    """Filterable fields, read from the dataset's own profile.

    Nothing here is hard-coded: the columns, their kinds and their values all
    come from the loaded frame, so a dataset with no region column simply does
    not offer a region filter.
    """
    dashboard = await get_dashboard(session, user, dashboard_id)
    loaded = await load_source(session, storage, user, dashboard)
    frame = loaded.frame
    model = semantic_columns.detect(frame)
    roles = {column: role for role, column in model.roles.items()}

    fields: list[FilterField] = []
    for name in frame.columns:
        column = str(name)
        detected = dataset_profiling.detect_type(frame[name])
        series = frame[name].dropna()

        if detected is DetectedType.DATETIME:
            parsed = pd.to_datetime(series, errors="coerce").dropna()
            fields.append(
                FilterField(
                    column=column,
                    kind="date",
                    minimum=parsed.min().isoformat() if not parsed.empty else None,
                    maximum=parsed.max().isoformat() if not parsed.empty else None,
                    role=roles.get(column),
                )
            )
        elif detected in (DetectedType.STRING, DetectedType.BOOLEAN):
            unique = series.astype(str).nunique()
            # A near-unique text column is an identifier, not something a user
            # would ever pick a value from.
            if unique > MAX_FILTER_CARDINALITY:
                continue
            counts = series.astype(str).value_counts().head(MAX_FILTER_VALUES)
            fields.append(
                FilterField(
                    column=column,
                    kind="categorical",
                    values=[str(index) for index in counts.index],
                    role=roles.get(column),
                )
            )
        elif detected in (DetectedType.INTEGER, DetectedType.FLOAT):
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            if numeric.empty:
                continue
            fields.append(
                FilterField(
                    column=column,
                    kind="numeric",
                    minimum=float(numeric.min()),
                    maximum=float(numeric.max()),
                    role=roles.get(column),
                )
            )

    return DashboardFilterOptions(
        dataset_id=loaded.dataset.id, version_id=loaded.version_id, fields=fields
    )


async def templates_for_dataset(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> DashboardTemplateList:
    """Templates and starter widgets, reduced to what this dataset supports."""
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    model = semantic_columns.detect(loaded.frame)
    return DashboardTemplateList(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        templates=dashboard_templates.available_templates(model),
        suggestions=dashboard_templates.suggestions(model),
    )
