"""dashboards and dashboard_widgets

A dashboard stores what to ask, never the answers: widget configurations are
validated Pydantic models serialised to JSON, and values are resolved at
refresh time against the pinned dataset version.

Revision ID: 0008_dashboards
Revises: 0007_insight_runs
Create Date: 2026-08-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_dashboards"
down_revision: str | None = "0007_insight_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

#: VARCHAR + CHECK, matching app.models.dataset._enum_column.
WIDGET_TYPE = sa.Enum(
    "kpi",
    "chart",
    "table",
    "ai_insight",
    "recommendation",
    "text",
    "nlq_result",
    "advanced",
    native_enum=False,
    length=16,
    name="widgettype",
)


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("layout_columns", sa.Integer(), nullable=False),
        sa.Column("filters", JSON_COLUMN, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_dashboards_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_dashboards_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_dashboards_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_dashboards_dataset_version_id_dataset_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboards")),
    )
    op.create_index(op.f("ix_dashboards_user_id"), "dashboards", ["user_id"], unique=False)
    op.create_index(op.f("ix_dashboards_project_id"), "dashboards", ["project_id"], unique=False)
    op.create_index(op.f("ix_dashboards_dataset_id"), "dashboards", ["dataset_id"], unique=False)

    op.create_table(
        "dashboard_widgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dashboard_id", sa.Uuid(), nullable=False),
        sa.Column("widget_type", WIDGET_TYPE, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("position_x", sa.Integer(), nullable=False),
        sa.Column("position_y", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("configuration", JSON_COLUMN, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dashboard_id"],
            ["dashboards.id"],
            name=op.f("fk_dashboard_widgets_dashboard_id_dashboards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboard_widgets")),
    )
    op.create_index(
        op.f("ix_dashboard_widgets_dashboard_id"),
        "dashboard_widgets",
        ["dashboard_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dashboard_widgets_dashboard_id"), table_name="dashboard_widgets")
    op.drop_table("dashboard_widgets")
    op.drop_index(op.f("ix_dashboards_dataset_id"), table_name="dashboards")
    op.drop_index(op.f("ix_dashboards_project_id"), table_name="dashboards")
    op.drop_index(op.f("ix_dashboards_user_id"), table_name="dashboards")
    op.drop_table("dashboards")
