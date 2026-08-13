"""datasets: uploaded files belonging to a project

Adds the `datasets` table. File bytes live in the storage provider; this table
holds only the storage key plus extracted metadata.

Deleting a project cascades to its datasets, matching the existing
workspace -> project deletion policy. Stored files are removed by the dataset
service.

Revision ID: 0003_datasets
Revises: 0002_auth_user_fields
Create Date: 2026-08-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_datasets"
down_revision: str | None = "0002_auth_user_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# VARCHAR + CHECK rather than a native PostgreSQL ENUM, so adding a status
# later is a constraint change instead of an ALTER TYPE migration.
FILE_TYPE = sa.Enum("csv", "xlsx", name="datasetfiletype", native_enum=False, length=16)
STATUS = sa.Enum(
    "uploading",
    "processing",
    "ready",
    "failed",
    name="datasetstatus",
    native_enum=False,
    length=16,
)

# JSONB on PostgreSQL, plain JSON elsewhere (the test suite runs on SQLite).
COLUMNS_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("file_type", FILE_TYPE, nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("status", STATUS, nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("columns", COLUMNS_JSON, nullable=True),
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
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_datasets_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
    )
    op.create_index(op.f("ix_datasets_project_id"), "datasets", ["project_id"], unique=False)
    op.create_index(op.f("ix_datasets_status"), "datasets", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_datasets_status"), table_name="datasets")
    op.drop_index(op.f("ix_datasets_project_id"), table_name="datasets")
    op.drop_table("datasets")
