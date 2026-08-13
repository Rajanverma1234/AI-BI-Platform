"""auth: rename user password/name columns and require a password hash

Renames rather than drop/create so no existing user data is lost:
  hashed_password -> password_hash  (now NOT NULL)
  full_name       -> display_name

Rows that predate authentication have no password. They are backfilled with an
unusable sentinel ('!') which is not a valid Argon2 hash, so those accounts
cannot log in until a password is set - see app.core.security.

Revision ID: 0002_auth_user_fields
Revises: 0001_initial
Create Date: 2026-08-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_auth_user_fields"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNUSABLE_PASSWORD_HASH = "!"


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("hashed_password", new_column_name="password_hash")
        batch_op.alter_column("full_name", new_column_name="display_name")

    # Backfill before tightening the constraint so the ALTER cannot fail.
    backfill = sa.text("UPDATE users SET password_hash = :sentinel WHERE password_hash IS NULL")
    op.execute(backfill.bindparams(sentinel=UNUSABLE_PASSWORD_HASH))

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.alter_column("password_hash", new_column_name="hashed_password")
        batch_op.alter_column("display_name", new_column_name="full_name")
