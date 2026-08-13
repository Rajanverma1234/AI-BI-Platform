"""Project model - a unit of BI work inside a workspace."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.dataset import Dataset
    from app.models.workspace import Workspace


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "slug"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Unique per workspace rather than globally - see __table_args__.
    slug: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    # Matches the workspace -> project policy: deleting a project removes its
    # datasets. Stored files are cleaned up by the dataset service.
    datasets: Mapped[list[Dataset]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Project id={self.id} slug={self.slug!r}>"
