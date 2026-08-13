"""dataset_versions: cleaned outputs derived from an uploaded dataset

The original `datasets` row and its stored file are never modified by cleaning;
each run appends a row here pointing at a new stored object.

`source_version_id` is self-referential and ON DELETE SET NULL: dropping an
intermediate version leaves later ones intact (their lineage is simply cut)
rather than cascading the whole chain away.

Revision ID: 0004_dataset_versions
Revises: 0003_datasets
Create Date: 2026-08-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_dataset_versions"
down_revision: str | None = "0003_datasets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILE_TYPE = sa.Enum("csv", "xlsx", name="datasetfiletype", native_enum=False, length=16)
JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("file_type", FILE_TYPE, nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("columns", JSON_COLUMN, nullable=True),
        sa.Column("operations", JSON_COLUMN, nullable=False),
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
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_dataset_versions_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_dataset_versions_source_version_id_dataset_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_versions")),
        sa.UniqueConstraint(
            "dataset_id",
            "version_number",
            name=op.f("uq_dataset_versions_dataset_id_version_number"),
        ),
    )
    op.create_index(
        op.f("ix_dataset_versions_dataset_id"), "dataset_versions", ["dataset_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dataset_versions_dataset_id"), table_name="dataset_versions")
    op.drop_table("dataset_versions")
