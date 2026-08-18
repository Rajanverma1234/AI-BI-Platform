"""nlq_queries: recorded natural-language questions and their query plans

Stores the question, the validated plan that was executed and the outcome.
No credentials, provider configuration or result rows are persisted.

Revision ID: 0005_nlq_queries
Revises: 0004_dataset_versions
Create Date: 2026-08-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_nlq_queries"
down_revision: str | None = "0004_dataset_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "nlq_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("plan", JSON_COLUMN, nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
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
            ["user_id"], ["users.id"], name=op.f("fk_nlq_queries_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_nlq_queries_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_nlq_queries_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_nlq_queries_dataset_version_id_dataset_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nlq_queries")),
    )
    op.create_index(op.f("ix_nlq_queries_user_id"), "nlq_queries", ["user_id"], unique=False)
    op.create_index(op.f("ix_nlq_queries_project_id"), "nlq_queries", ["project_id"], unique=False)
    op.create_index(op.f("ix_nlq_queries_dataset_id"), "nlq_queries", ["dataset_id"], unique=False)
    op.create_index(op.f("ix_nlq_queries_status"), "nlq_queries", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_nlq_queries_status"), table_name="nlq_queries")
    op.drop_index(op.f("ix_nlq_queries_dataset_id"), table_name="nlq_queries")
    op.drop_index(op.f("ix_nlq_queries_project_id"), table_name="nlq_queries")
    op.drop_index(op.f("ix_nlq_queries_user_id"), table_name="nlq_queries")
    op.drop_table("nlq_queries")
