"""Recorded natural-language queries.

Stores the question and the structured plan that answered it, so a user can
revisit past questions and an operator can audit what was executed. No
credentials, provider keys or raw result rows are kept.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.dataset import JSONColumn

if TYPE_CHECKING:
    from app.models.dataset import Dataset


class NlqQuery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nlq_queries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Null when the question ran against the original upload.
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )

    question: Mapped[str] = mapped_column(String(500), nullable=False)
    #: The validated plan that was executed, for auditing and replay.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    #: User-facing failure reason; never a traceback.
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    dataset: Mapped[Dataset] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<NlqQuery {self.id} status={self.status}>"
