"""Dashboards and their widgets.

A dashboard is a saved arrangement of the platform's existing analytics: each
widget stores *what to ask*, never the answer. Values are always resolved at
refresh time against the dataset version the dashboard is pinned to, so a
dashboard cannot show a figure that is no longer true of its data.

``configuration`` is a validated Pydantic model serialised to JSON, never a
free-form blob and never executable: a widget can name a column, a metric and a
filter, and nothing else. That is what keeps "saved dashboard" from becoming
"stored code execution".

The dataset version is recorded explicitly rather than resolved as "latest".
Cleaning a dataset produces a new version; a dashboard must not silently start
reporting on data its author never saw.
"""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.dataset import JSONColumn, _enum_column

if TYPE_CHECKING:
    from app.models.dataset import Dataset


class WidgetType(enum.StrEnum):
    """What a widget shows.

    Every chart shape (line, bar, pie, donut, area, scatter, histogram, box) is
    the single ``CHART`` type carrying an existing ``ChartType`` in its
    configuration - the platform has one charting pipeline and this reuses it
    rather than adding a parallel set of widget types.
    """

    KPI = "kpi"
    CHART = "chart"
    TABLE = "table"
    AI_INSIGHT = "ai_insight"
    RECOMMENDATION = "recommendation"
    TEXT = "text"
    NLQ_RESULT = "nlq_result"
    ADVANCED = "advanced"


class Dashboard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dashboards"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: Null means the original upload. Never resolved as "whichever is latest".
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    #: Grid width in columns (1-4); widget widths are expressed against this.
    layout_columns: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    #: Serialised FilterSet applied to every compatible widget.
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)

    dataset: Mapped[Dataset] = relationship()
    widgets: Mapped[list[DashboardWidget]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardWidget.position_y, DashboardWidget.position_x",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Dashboard {self.id} name={self.name!r}>"


class DashboardWidget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dashboard_widgets"

    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True, nullable=False
    )
    widget_type: Mapped[WidgetType] = mapped_column(_enum_column(WidgetType), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Position is stored as columns rather than pixels, so the same layout
    # reflows correctly at any screen width.
    position_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: A validated widget configuration model, serialised. Never executable.
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False)

    dashboard: Mapped[Dashboard] = relationship(back_populates="widgets")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DashboardWidget {self.id} type={self.widget_type.value}>"
