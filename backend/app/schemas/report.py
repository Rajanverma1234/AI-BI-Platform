"""Report schemas.

The important type here is :class:`ReportData`: one canonical, already-computed
representation of a report that every renderer consumes. PDF, XLSX, CSV and
PPTX all walk the same sections, so a figure is calculated exactly once and the
four formats can never disagree with each other or with the on-screen preview.

A section is deliberately generic - paragraphs, metrics, tables and bullets -
rather than one shape per analysis. That is what lets a renderer support a new
section without being changed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.report import ReportFileFormat, ReportStatus, ReportTemplateName
from app.schemas.common import ORMModel, Page

#: A table cell. Numbers stay numeric so XLSX can write real numbers; the
#: text-based renderers format them through ``report_builder.cell_text``.
ReportCell = str | float | int | None


class ReportSectionKey(enum.StrEnum):
    """Every section the platform can produce.

    Which of these a given report actually contains depends on the template and
    on what the dataset supports - nothing is assumed about the schema.
    """

    EXECUTIVE_SUMMARY = "executive_summary"
    #: Sections fed by the AI Insights engine rather than by one analysis.
    BUSINESS_HEALTH = "business_health"
    CRITICAL_INSIGHTS = "critical_insights"
    OPPORTUNITIES = "opportunities"
    RISKS = "risks"
    DATASET_OVERVIEW = "dataset_overview"
    DATA_QUALITY = "data_quality"
    KPIS = "kpis"
    EDA = "eda"
    TRENDS = "trends"
    SEGMENTATION = "segmentation"
    ABC = "abc"
    PARETO = "pareto"
    RFM = "rfm"
    COHORT = "cohort"
    CHURN = "churn"
    CORRELATION = "correlation"
    OUTLIERS = "outliers"
    FORECAST = "forecast"
    AI_INSIGHTS = "ai_insights"
    RECOMMENDATIONS = "recommendations"


class ReportMetric(BaseModel):
    """One headline figure, already formatted for display."""

    label: str
    value: str
    detail: str | None = None


class ReportTable(BaseModel):
    title: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[ReportCell]] = Field(default_factory=list)
    #: Set when rows were capped, so every renderer says so identically.
    note: str | None = None


class ReportSection(BaseModel):
    key: ReportSectionKey
    title: str
    #: Prose paragraphs. Deterministic unless the section is AI-generated.
    narrative: list[str] = Field(default_factory=list)
    metrics: list[ReportMetric] = Field(default_factory=list)
    tables: list[ReportTable] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    #: Why the section is empty. Set instead of omitting the section, so the
    #: report states what could not be produced rather than staying silent.
    unavailable_reason: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.narrative or self.metrics or self.tables or self.bullets)


class ReportData(BaseModel):
    """A fully computed report, independent of any output format."""

    title: str
    subtitle: str | None = None
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    version_id: uuid.UUID | None = None
    version_label: str
    template: ReportTemplateName
    generated_at: datetime
    #: Display name of the requesting user; no email or id is embedded.
    generated_by: str
    row_count: int
    column_count: int
    sections: list[ReportSection] = Field(default_factory=list)
    #: True when an AI provider contributed narrative to this report.
    ai_available: bool = False
    ai_status: str | None = None
    #: Sections that were requested but could not be produced, with reasons.
    skipped: list[dict[str, str]] = Field(default_factory=list)


# --- Requests ----------------------------------------------------------------


class ReportGenerateRequest(BaseModel):
    version_id: uuid.UUID | None = None
    template: ReportTemplateName = ReportTemplateName.EXECUTIVE
    file_format: ReportFileFormat = ReportFileFormat.PDF
    #: Overrides the template's default sections. Unsupported ones are
    #: reported in ``skipped`` rather than silently dropped.
    sections: list[ReportSectionKey] | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    #: Ask the configured AI provider for narrative. Falls back to the
    #: deterministic summary when no provider is configured.
    include_ai: bool = True


class ReportPreviewRequest(BaseModel):
    version_id: uuid.UUID | None = None
    template: ReportTemplateName = ReportTemplateName.EXECUTIVE
    sections: list[ReportSectionKey] | None = Field(default=None, max_length=20)
    title: str | None = Field(default=None, max_length=200)
    include_ai: bool = True


# --- Responses ---------------------------------------------------------------


class SectionAvailability(BaseModel):
    key: ReportSectionKey
    title: str
    available: bool
    #: Present only when unavailable: what the dataset would need.
    reason: str | None = None
    required_roles: list[str] = Field(default_factory=list)


class ReportTemplateInfo(BaseModel):
    template: ReportTemplateName
    name: str
    description: str
    #: The template's sections that this dataset can actually produce.
    sections: list[ReportSectionKey] = Field(default_factory=list)
    unavailable_sections: list[ReportSectionKey] = Field(default_factory=list)


class ReportOptionsResponse(BaseModel):
    """What this dataset can be reported on, and in which formats."""

    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    templates: list[ReportTemplateInfo] = Field(default_factory=list)
    sections: list[SectionAvailability] = Field(default_factory=list)
    formats: list[ReportFileFormat] = Field(default_factory=list)
    detected_columns: dict[str, str] = Field(default_factory=dict)


class ReportResponse(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_version_id: uuid.UUID | None = None
    name: str
    template: ReportTemplateName
    file_format: ReportFileFormat
    sections: list[str] = Field(default_factory=list)
    status: ReportStatus
    file_size: int
    #: Set only when status is "failed"; safe wording, never a traceback.
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


#: Paginated envelope returned by GET .../reports.
ReportListResponse = Page[ReportResponse]
