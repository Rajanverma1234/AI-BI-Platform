"""A recorded insight-generation run.

The full report is stored as JSON rather than shredded into tables: it is a
derived snapshot of one moment's analysis, always rewritten wholesale, and
never queried field-by-field. What *is* indexed are the things a user filters
history by - dataset, version and status.

``analysis_version`` is stored alongside the result so a run produced by older
detection rules can be marked stale instead of being presented as current.

No provider keys, prompts or raw dataset rows are persisted.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.dataset import JSONColumn, _enum_column
from app.schemas.insights import RunStatus

if TYPE_CHECKING:
    from app.models.dataset import Dataset


class InsightRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "insight_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Null when the run analysed the original upload.
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )

    #: Detection-pipeline version that produced ``result``.
    analysis_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[RunStatus] = mapped_column(_enum_column(RunStatus), nullable=False, index=True)

    #: Denormalised for the history list, so showing it needs no JSON parsing.
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    health_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    insight_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    ai_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Why the AI layer was skipped or failed. Never a traceback or a key.
    ai_status: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: The serialised InsightReport. Null only when the run failed.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    #: Safe, user-facing failure reason.
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    dataset: Mapped[Dataset] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<InsightRun {self.id} status={self.status.value} score={self.health_score}>"
