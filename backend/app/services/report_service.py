"""Report orchestration: authorise, compute once, render, store, record.

The pipeline is deliberately linear:

    dataset_access.load_for_user     one authorisation gate, one file read
    -> profile + quality             computed once, shared with the analyst
    -> ai_analyst_service            deterministic findings (+ optional AI)
    -> report_builder                one canonical ReportData
    -> report_<format>.render        bytes
    -> StorageProvider + Report row  the file, and a record of the request

Because every renderer reads the same :class:`ReportData`, a KPI is calculated
exactly once no matter how many formats are exported, and the PDF can never
disagree with the XLSX or with the on-screen preview.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError, StorageError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.models.report import Report, ReportFileFormat, ReportStatus, ReportTemplateName
from app.models.user import User
from app.schemas.report import (
    ReportData,
    ReportGenerateRequest,
    ReportOptionsResponse,
    ReportPreviewRequest,
    ReportSectionKey,
    ReportTemplateInfo,
    SectionAvailability,
)
from app.services import (
    advanced_analytics_service,
    ai_analyst_service,
    data_quality,
    dataset_access,
    dataset_profiling,
    insights_service,
    report_builder,
    report_csv,
    report_pdf,
    report_pptx,
    report_xlsx,
    semantic_columns,
)
from app.storage.base import StorageProvider, chunks_of

logger = get_logger(__name__)

REPORT_NOT_FOUND = "Report not found."

#: Renderer and content type per format. Adding a format means adding a module
#: and one entry here - no service or endpoint change.
RENDERERS = {
    ReportFileFormat.PDF: (report_pdf.render, report_pdf.CONTENT_TYPE),
    ReportFileFormat.XLSX: (report_xlsx.render, report_xlsx.CONTENT_TYPE),
    ReportFileFormat.CSV: (report_csv.render, report_csv.CONTENT_TYPE),
    ReportFileFormat.PPTX: (report_pptx.render, report_pptx.CONTENT_TYPE),
}

#: Filename slug: lowercase alphanumerics and single hyphens, nothing else.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_MAX_SLUG = 60


def content_type(file_format: ReportFileFormat) -> str:
    return RENDERERS[file_format][1]


def slugify(value: str, fallback: str = "report") -> str:
    """A filename-safe slug.

    Storage keys are built from this, so it must never produce a separator, a
    dot segment or an empty string - path traversal cannot start here.
    """
    slug = _SLUG_STRIP.sub("-", value.lower()).strip("-")[:_MAX_SLUG].strip("-")
    return slug or fallback


def storage_key_for(report_id: uuid.UUID, name: str, file_format: ReportFileFormat) -> str:
    """Server-generated key. No part of it is taken verbatim from the client."""
    return f"reports/{report_id}/{slugify(name)}.{file_format.value}"


def download_filename(report: Report) -> str:
    return f"{slugify(report.name)}.{report.file_format.value}"


# --- Loading -----------------------------------------------------------------


@dataclass
class _Computed:
    """Everything the builder needs, computed exactly once."""

    loaded: dataset_access.LoadedDataset
    data: ReportData


async def _compute(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    *,
    version_id: uuid.UUID | None,
    template: ReportTemplateName,
    sections: list[ReportSectionKey] | None,
    title: str | None,
    include_ai: bool,
) -> _Computed:
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

    if include_ai:
        narrative, status = await ai_analyst_service.interpret(analyst)
        analyst.ai = narrative
        analyst.ai_available = narrative is not None
        analyst.ai_status = status
    else:
        analyst.ai_status = "AI narrative was not requested."

    # Business health, opportunities and risks come from the AI Insights engine.
    # Building it runs RFM and churn, so it is only done when one of those
    # sections was actually asked for.
    insights = None
    requested = set(report_builder.resolve_sections(template, sections))
    if requested & set(report_builder.INSIGHT_SECTIONS):
        insights = insights_service.build_deterministic(
            frame,
            loaded,
            analyst,
            quality,
            project_id=project_id,
            generated_by=user.display_name or user.email,
        )

    data = report_builder.build(
        frame,
        loaded,
        analyst,
        profile,
        quality,
        project_id=project_id,
        template=template,
        sections=sections,
        title=title,
        generated_by=user.display_name or user.email,
        insights=insights,
    )
    return _Computed(loaded=loaded, data=data)


# --- Options -----------------------------------------------------------------


async def options(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> ReportOptionsResponse:
    """Which templates, sections and formats this dataset supports.

    Only offers what the dataset can actually produce; anything unavailable is
    returned with the reason so the UI can explain rather than just hide it.
    """
    loaded = await dataset_access.load_for_user(
        session, storage, user, project_id, dataset_id, version_id
    )
    model = semantic_columns.detect(loaded.frame)
    supported, reasons = report_builder.available_sections(model)
    supported_set = set(supported)

    sections = [
        SectionAvailability(
            key=key,
            title=report_builder.SECTION_TITLES[key],
            available=key in supported_set,
            reason=reasons.get(key),
            required_roles=report_builder.SECTION_REQUIREMENTS[key],
        )
        for key in report_builder.SECTION_ORDER
    ]

    templates = []
    for template in ReportTemplateName:
        keys = report_builder.template_sections(template)
        templates.append(
            ReportTemplateInfo(
                template=template,
                name=report_builder.TEMPLATES[template]["name"],
                description=report_builder.TEMPLATES[template]["description"],
                sections=[key for key in keys if key in supported_set],
                unavailable_sections=[key for key in keys if key not in supported_set],
            )
        )

    detected = {
        role: column
        for role, column in advanced_analytics_service.present_roles(model).items()
        if column
    }

    return ReportOptionsResponse(
        dataset_id=loaded.dataset.id,
        version_id=loaded.version_id,
        templates=templates,
        sections=sections,
        formats=list(ReportFileFormat),
        detected_columns=detected,
    )


# --- Preview -----------------------------------------------------------------


async def preview(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: ReportPreviewRequest,
) -> ReportData:
    """The exact report the renderers would receive, as JSON.

    The on-screen preview and the downloaded file therefore show identical
    figures: they are the same object.
    """
    computed = await _compute(
        session,
        storage,
        user,
        project_id,
        dataset_id,
        version_id=request.version_id,
        template=request.template,
        sections=request.sections,
        title=request.title,
        include_ai=request.include_ai,
    )
    return computed.data


# --- Generation --------------------------------------------------------------


async def as_stream(payload: bytes) -> AsyncIterator[bytes]:
    """Adapt rendered bytes to the provider's chunked upload contract.

    Public because the dashboard exporter reuses this whole storage path
    rather than reimplementing it.
    """
    for chunk in chunks_of(payload):
        yield chunk


async def generate(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: ReportGenerateRequest,
) -> Report:
    """Build, render and store one report.

    A rendering failure is recorded as a ``failed`` report rather than raised,
    matching how a failed upload is reported, so the attempt stays visible in
    the user's history with a reason.
    """
    computed = await _compute(
        session,
        storage,
        user,
        project_id,
        dataset_id,
        version_id=request.version_id,
        template=request.template,
        sections=request.sections,
        title=request.title,
        include_ai=request.include_ai,
    )
    data = computed.data

    report = Report(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project_id,
        dataset_id=computed.loaded.dataset.id,
        dataset_version_id=computed.loaded.version_id,
        name=(request.name or data.title)[:255],
        template=request.template,
        file_format=request.file_format,
        sections=[section.key.value for section in data.sections],
        status=ReportStatus.READY,
        file_size=0,
    )

    render, _ = RENDERERS[request.file_format]
    try:
        payload = render(data)
    except Exception:
        logger.exception("Rendering a %s report failed", request.file_format.value)
        report.status = ReportStatus.FAILED
        report.error_message = (
            f"The {request.file_format.value.upper()} file could not be produced "
            "from this report. Try another format or fewer sections."
        )
        session.add(report)
        await session.flush()
        return report

    key = storage_key_for(report.id, report.name, request.file_format)
    try:
        stored = await storage.upload(key, as_stream(payload))
    except AppError:
        raise
    except Exception as exc:  # pragma: no cover - provider-specific failures
        logger.exception("Storing report %s failed", report.id)
        raise StorageError("The report could not be stored.") from exc

    report.storage_key = stored.storage_key
    report.file_size = stored.size_bytes
    session.add(report)
    await session.flush()
    return report


# --- History -----------------------------------------------------------------


async def list_reports(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    pagination: Pagination,
) -> tuple[list[Report], int]:
    """This user's reports for this dataset, newest first."""
    # Authorises the dataset before any report row is exposed.
    await dataset_access.load_for_user(session, storage, user, project_id, dataset_id, None)

    mine = (Report.dataset_id == dataset_id) & (Report.user_id == user.id)
    total = await session.scalar(select(func.count()).select_from(Report).where(mine)) or 0
    result = await session.execute(
        select(Report)
        .where(mine)
        .order_by(desc(Report.created_at))
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    return list(result.scalars().all()), total


async def get_report(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    report_id: uuid.UUID,
) -> Report:
    """Load one report, scoped to the caller and to an authorised dataset."""
    await dataset_access.load_for_user(session, storage, user, project_id, dataset_id, None)

    result = await session.execute(
        select(Report).where(
            Report.id == report_id,
            # Scoping by dataset and user prevents reading another tenant's row
            # even if an id is guessed.
            Report.dataset_id == dataset_id,
            Report.user_id == user.id,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise NotFoundError(REPORT_NOT_FOUND)
    return report


async def download(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    report_id: uuid.UUID,
) -> tuple[Report, bytes]:
    """The stored bytes for a ready report."""
    report = await get_report(session, storage, user, project_id, dataset_id, report_id)

    if report.status is not ReportStatus.READY or not report.storage_key:
        raise NotFoundError(
            report.error_message or "This report has no file to download."
        )

    try:
        with storage.open(report.storage_key) as handle:
            payload = handle.read()
    except AppError:
        raise
    except Exception as exc:  # pragma: no cover - provider-specific failures
        logger.exception("Reading report %s failed", report.id)
        raise StorageError("The stored report could not be read.") from exc

    return report, payload


async def delete_report(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    report_id: uuid.UUID,
) -> None:
    """Remove the record and the stored file."""
    report = await get_report(session, storage, user, project_id, dataset_id, report_id)
    key = report.storage_key

    await session.delete(report)
    await session.flush()

    if key:
        # After the row is gone: an orphaned file is recoverable, a row
        # pointing at a deleted file is not.
        await storage.delete(key)
