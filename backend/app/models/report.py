"""Generated report - a rendered export of a dataset's analysis.

The rendered bytes live in the storage provider, exactly like dataset files;
the row records only what was asked for (template, sections, format) plus the
key needed to fetch the result. Keeping the request means a report can be
regenerated against a newer version, and the history is auditable.

Section keys are stored as plain strings rather than a database enum, so
adding a section later is a code change and not a migration.
"""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.dataset import JSONColumn, _enum_column

if TYPE_CHECKING:
    from app.models.dataset import Dataset


class ReportStatus(enum.StrEnum):
    """Outcome of a generation run."""

    READY = "ready"
    #: Rendering failed; ``error_message`` says why. Kept rather than discarded
    #: so the user sees the attempt in their history instead of nothing.
    FAILED = "failed"


class ReportTemplateName(enum.StrEnum):
    EXECUTIVE = "executive"
    SALES = "sales"
    CUSTOMER = "customer"
    FULL = "full"


class ReportFileFormat(enum.StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"
    CSV = "csv"
    PPTX = "pptx"


class Report(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    #: Who generated it. Reports are listed per user, like NLQ history.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Null when the report was built from the original upload.
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[ReportTemplateName] = mapped_column(
        _enum_column(ReportTemplateName), nullable=False
    )
    file_format: Mapped[ReportFileFormat] = mapped_column(
        _enum_column(ReportFileFormat), nullable=False
    )
    #: The section keys that were requested, in the order they were rendered.
    sections: Mapped[list[str]] = mapped_column(JSONColumn, nullable=False)

    status: Mapped[ReportStatus] = mapped_column(
        _enum_column(ReportStatus), nullable=False, index=True
    )
    #: Server-generated storage key; never built from user input.
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: Safe, user-facing reason a report failed. Never a traceback or a path.
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    dataset: Mapped[Dataset] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Report {self.id} {self.file_format.value} status={self.status.value}>"
