"""Dataset model - an uploaded file belonging to a project.

Raw file bytes live in the storage provider, never in PostgreSQL; the row
holds only the key needed to retrieve them plus extracted metadata.
"""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.dataset_version import DatasetVersion
    from app.models.project import Project

#: JSONB on PostgreSQL, plain JSON elsewhere (the test suite runs on SQLite).
JSONColumn = JSON().with_variant(JSONB(), "postgresql")


def _enum_column(enum_type: type[enum.Enum]) -> Enum:
    """VARCHAR + CHECK rather than a native PostgreSQL ENUM.

    Adding a value later becomes a constraint change instead of an ALTER TYPE
    migration, and the same DDL works on SQLite for the test suite.
    """
    return Enum(
        enum_type,
        native_enum=False,
        length=16,
        values_callable=lambda e: [member.value for member in e],
    )


class DatasetStatus(enum.StrEnum):
    """Lifecycle of an uploaded dataset."""

    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DatasetFileType(enum.StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


class Dataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "datasets"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    #: Opaque key understood by the configured StorageProvider.
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[DatasetFileType] = mapped_column(
        _enum_column(DatasetFileType),
        nullable=False,
    )
    #: BigInteger so a file larger than 2 GB cannot overflow the column.
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[DatasetStatus] = mapped_column(
        _enum_column(DatasetStatus),
        nullable=False,
        default=DatasetStatus.UPLOADING,
        index=True,
    )
    #: Populated once processing succeeds.
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: [{"name": ..., "dtype": ..., "nullable": ...}, ...]
    columns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONColumn, nullable=True)
    #: Safe, user-facing reason a dataset failed. Never a traceback or path.
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="datasets")
    #: Cleaned versions derived from this upload. Deleting the dataset removes
    #: them; the original file itself is never modified by cleaning.
    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="DatasetVersion.version_number",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Dataset id={self.id} name={self.name!r} status={self.status.value}>"
