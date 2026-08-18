"""Export a dashboard through the existing report engine.

There is no second export engine here. A resolved dashboard is translated into
the canonical :class:`ReportData` - the same object the Reports module builds -
and then handed to the same renderers, the same storage provider and the same
``Report`` row. The exported file is therefore downloaded through the existing
``/reports/{id}/download`` route, and adding a fifth output format would still
be a one-line change in ``report_service.RENDERERS``.

Only the translation is new, and it is a translation: each widget becomes a
section of metrics, a table, or prose. No figure is recomputed on the way.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StorageError
from app.core.logging import get_logger
from app.models.report import Report, ReportFileFormat, ReportStatus, ReportTemplateName
from app.models.user import User
from app.schemas.dashboard import DashboardData, WidgetResult, WidgetStatus
from app.schemas.report import (
    ReportData,
    ReportMetric,
    ReportSection,
    ReportSectionKey,
    ReportTable,
)
from app.services import dashboard_service, report_service
from app.storage.base import StorageProvider

logger = get_logger(__name__)

#: Every dashboard widget renders under this key. The report's own section
#: vocabulary describes analyses, not dashboard tiles, so one generic key is
#: more honest than mislabelling a widget as an "executive summary".
_WIDGET_SECTION = ReportSectionKey.DATASET_OVERVIEW


def _format(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}" if value != int(value) else f"{int(value):,}"
    return str(value)


def _widget_section(widget: WidgetResult) -> ReportSection:
    """One widget as one report section."""
    if widget.status is WidgetStatus.ERROR:
        return ReportSection(
            key=_WIDGET_SECTION,
            title=widget.title,
            unavailable_reason=widget.error or "This widget could not be loaded.",
        )

    metrics: list[ReportMetric] = []
    tables: list[ReportTable] = []
    narrative: list[str] = []
    bullets: list[str] = []

    if widget.kpi is not None:
        result = widget.kpi.result
        metrics.append(
            ReportMetric(
                label=result.name,
                value=_format(result.value) if result.available else "Not available",
                detail=result.reason or result.column,
            )
        )
        if result.groups:
            tables.append(
                ReportTable(
                    columns=["Group", "Value"],
                    rows=[[item.group, item.value] for item in result.groups],
                )
            )

    if widget.chart is not None:
        chart = widget.chart
        narrative.append(
            f"{chart.chart_type.value.title()} chart of {chart.y_axis or 'value'} "
            f"by {chart.x_axis or 'category'}."
        )
        if chart.labels and chart.series:
            # A chart becomes its underlying numbers: a static export cannot
            # be interactive, and the figures are what the reader needs.
            tables.append(
                ReportTable(
                    columns=[chart.x_axis or "Category", *[s.name for s in chart.series]],
                    rows=[
                        [label, *[series.data[index] for series in chart.series]]
                        for index, label in enumerate(chart.labels)
                    ],
                )
            )
        elif chart.points:
            tables.append(
                ReportTable(
                    columns=[chart.x_axis or "x", chart.y_axis or "y"],
                    rows=[[point.x, point.y] for point in chart.points],
                )
            )

    if widget.table is not None:
        table = widget.table
        tables.append(
            ReportTable(
                columns=table.columns,
                rows=[[row.get(column) for column in table.columns] for row in table.rows],
                note=(
                    f"Showing {len(table.rows):,} of {table.row_count:,} rows."
                    if table.truncated
                    else None
                ),
            )
        )

    if widget.insight is not None:
        insight = widget.insight
        if insight.health_score is not None:
            metrics.append(
                ReportMetric(
                    label="Business health",
                    value=f"{insight.health_score}/100",
                    detail=insight.health_rating,
                )
            )
        tables.append(
            ReportTable(
                columns=["Finding", "Category", "Severity", "Priority"],
                rows=[
                    [
                        item.title,
                        item.category.value.replace("_", " "),
                        item.severity.value,
                        item.priority.value,
                    ]
                    for item in insight.insights
                ],
            )
        )
        bullets.extend(f"{item.title}: {item.summary}" for item in insight.insights)
        if insight.stale:
            narrative.append(
                "These insights were generated for a different dataset version and "
                "may not reflect the data in this export."
            )

    if widget.recommendation is not None:
        tables.append(
            ReportTable(
                columns=["Priority", "Action", "Why", "Potential impact"],
                rows=[
                    [item.priority.value, item.action, item.reason, item.expected_impact]
                    for item in widget.recommendation.recommendations
                ],
            )
        )

    if widget.text is not None:
        narrative.append(widget.text.content)

    if widget.nlq is not None:
        nlq = widget.nlq
        narrative.append(f"Question: {nlq.question}")
        narrative.append(nlq.answer)
        if nlq.rows:
            tables.append(
                ReportTable(
                    columns=nlq.columns,
                    rows=[[row.get(column) for column in nlq.columns] for row in nlq.rows],
                )
            )

    if widget.advanced is not None:
        advanced = widget.advanced
        metrics.extend(
            ReportMetric(
                label=str(item.get("label")),
                value=f"{_format(item.get('value'))}{item.get('suffix', '')}",
            )
            for item in advanced.metrics
        )
        if advanced.rows:
            tables.append(
                ReportTable(
                    columns=advanced.columns,
                    rows=[
                        [row.get(column) for column in advanced.columns]
                        for row in advanced.rows
                    ],
                )
            )
        if advanced.note:
            narrative.append(advanced.note)

    return ReportSection(
        key=_WIDGET_SECTION,
        title=widget.title,
        narrative=narrative,
        metrics=metrics,
        tables=tables,
        bullets=bullets[:8],
    )


def to_report_data(
    dashboard: DashboardData, generated_by: str, project_id: uuid.UUID
) -> ReportData:
    """Translate a resolved dashboard into the canonical report model."""
    subtitle = dashboard.description or "Dashboard export"
    sections = [_widget_section(widget) for widget in dashboard.widgets]

    skipped = [
        {"section": widget.title, "reason": widget.error or "This widget could not be loaded."}
        for widget in dashboard.widgets
        if widget.status is WidgetStatus.ERROR
    ]

    return ReportData(
        title=dashboard.name,
        subtitle=subtitle,
        project_id=project_id,
        dataset_id=dashboard.dataset_id,
        dataset_name=dashboard.dataset_name,
        version_id=dashboard.version_id,
        version_label=dashboard.version_label,
        template=ReportTemplateName.FULL,
        generated_at=dashboard.refreshed_at,
        generated_by=generated_by,
        row_count=dashboard.filtered_row_count,
        column_count=0,
        sections=[section for section in sections if not section.is_empty],
        skipped=skipped,
    )


async def export(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    dashboard_id: uuid.UUID,
    file_format: ReportFileFormat,
) -> Report:
    """Refresh the dashboard, render it, and store it as an ordinary report.

    The result is a normal ``Report`` row, so it appears in the dataset's
    report history and downloads through the existing route.
    """
    data = await dashboard_service.refresh(session, storage, user, dashboard_id)
    dashboard = await dashboard_service.get_dashboard(session, user, dashboard_id)

    report_data = to_report_data(
        data, user.display_name or user.email, dashboard.project_id
    )

    report = Report(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=dashboard.project_id,
        dataset_id=dashboard.dataset_id,
        dataset_version_id=dashboard.dataset_version_id,
        name=f"{dashboard.name} (dashboard)"[:255],
        template=ReportTemplateName.FULL,
        file_format=file_format,
        sections=[widget.title for widget in data.widgets],
        status=ReportStatus.READY,
        file_size=0,
    )

    render, _ = report_service.RENDERERS[file_format]
    try:
        payload = render(report_data)
    except Exception:
        logger.exception("Rendering dashboard %s as %s failed", dashboard_id, file_format.value)
        report.status = ReportStatus.FAILED
        report.error_message = (
            f"The {file_format.value.upper()} file could not be produced from this dashboard."
        )
        session.add(report)
        await session.flush()
        return report

    key = report_service.storage_key_for(report.id, report.name, file_format)
    try:
        stored = await storage.upload(key, report_service.as_stream(payload))
    except Exception as exc:  # pragma: no cover - provider-specific failures
        logger.exception("Storing dashboard export %s failed", report.id)
        raise StorageError("The dashboard export could not be stored.") from exc

    report.storage_key = stored.storage_key
    report.file_size = stored.size_bytes
    session.add(report)
    await session.flush()
    return report
