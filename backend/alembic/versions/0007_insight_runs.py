"""insight_runs: recorded AI insight generation runs

Stores the generated report as JSON along with the analysis version that
produced it, so an older run can be marked stale rather than shown as current.
No provider keys, prompts or dataset rows are persisted.

Revision ID: 0007_insight_runs
Revises: 0006_reports
Create Date: 2026-08-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_insight_runs"
down_revision: str | None = "0006_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "insight_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("analysis_version", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            # VARCHAR + CHECK, matching app.models.dataset._enum_column.
            sa.Enum("ready", "failed", native_enum=False, length=16, name="runstatus"),
            nullable=False,
        ),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column("health_rating", sa.String(length=20), nullable=True),
        sa.Column("insight_count", sa.Integer(), nullable=False),
        sa.Column("recommendation_count", sa.Integer(), nullable=False),
        sa.Column("ai_available", sa.Boolean(), nullable=False),
        sa.Column("ai_status", sa.String(length=500), nullable=True),
        sa.Column("result", JSON_COLUMN, nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_insight_runs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_insight_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_insight_runs_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_insight_runs_dataset_version_id_dataset_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_insight_runs")),
    )
    op.create_index(op.f("ix_insight_runs_user_id"), "insight_runs", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_insight_runs_project_id"), "insight_runs", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_insight_runs_dataset_id"), "insight_runs", ["dataset_id"], unique=False
    )
    op.create_index(op.f("ix_insight_runs_status"), "insight_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_insight_runs_status"), table_name="insight_runs")
    op.drop_index(op.f("ix_insight_runs_dataset_id"), table_name="insight_runs")
    op.drop_index(op.f("ix_insight_runs_project_id"), table_name="insight_runs")
    op.drop_index(op.f("ix_insight_runs_user_id"), table_name="insight_runs")
    op.drop_table("insight_runs")
