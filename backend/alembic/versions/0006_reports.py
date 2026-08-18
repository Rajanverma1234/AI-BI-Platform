"""reports: generated report exports

Records what was requested (template, sections, format) and where the rendered
file was stored. The bytes themselves live in the storage provider, never in
PostgreSQL.

Revision ID: 0006_reports
Revises: 0005_nlq_queries
Create Date: 2026-08-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_reports"
down_revision: str | None = "0005_nlq_queries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _enum(name: str, *values: str) -> sa.Enum:
    """VARCHAR + CHECK, matching ``app.models.dataset._enum_column``."""
    return sa.Enum(*values, native_enum=False, length=16, name=name)


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "template",
            _enum("reporttemplatename", "executive", "sales", "customer", "full"),
            nullable=False,
        ),
        sa.Column(
            "file_format",
            _enum("reportfileformat", "pdf", "xlsx", "csv", "pptx"),
            nullable=False,
        ),
        sa.Column("sections", JSON_COLUMN, nullable=False),
        sa.Column("status", _enum("reportstatus", "ready", "failed"), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
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
            ["user_id"], ["users.id"], name=op.f("fk_reports_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_reports_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_reports_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_reports_dataset_version_id_dataset_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_user_id"), "reports", ["user_id"], unique=False)
    op.create_index(op.f("ix_reports_project_id"), "reports", ["project_id"], unique=False)
    op.create_index(op.f("ix_reports_dataset_id"), "reports", ["dataset_id"], unique=False)
    op.create_index(op.f("ix_reports_status"), "reports", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reports_status"), table_name="reports")
    op.drop_index(op.f("ix_reports_dataset_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_project_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_user_id"), table_name="reports")
    op.drop_table("reports")
