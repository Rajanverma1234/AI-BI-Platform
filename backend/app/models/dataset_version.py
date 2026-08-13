"""Dataset version - the result of applying a cleaning pipeline.

The original upload is immutable: cleaning never rewrites the `datasets` row or
its stored file. Each run writes a new object to storage and records a new
version row, so the lineage
``original -> version 1 -> version 2`` is always reconstructible and a future
rollback only needs to select an earlier row.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.dataset import DatasetFileType, JSONColumn, _enum_column

if TYPE_CHECKING:
    from app.models.dataset import Dataset


class DatasetVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    # Version numbers are per dataset and allocated sequentially.
    __table_args__ = (UniqueConstraint("dataset_id", "version_number"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    #: The version this one was derived from; NULL means it came from the
    #: original upload. Self-referential so lineage survives deeper chains.
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[DatasetFileType] = mapped_column(
        _enum_column(DatasetFileType), nullable=False
    )
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    columns: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONColumn, nullable=True)
    #: The exact pipeline that produced this version, replayable as-is.
    operations: Mapped[list[dict[str, Any]]] = mapped_column(JSONColumn, nullable=False)

    dataset: Mapped[Dataset] = relationship(back_populates="versions")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DatasetVersion dataset={self.dataset_id} v{self.version_number}>"
