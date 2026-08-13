"""The Alembic migration chain must build the same schema as the models.

Runs against a throwaway SQLite file so it needs no PostgreSQL server; the
same revisions are applied to PostgreSQL by `alembic upgrade head`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.db.base import Base
from app.models import Project, User, Workspace  # noqa: F401  (register metadata)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_config(tmp_path: Path) -> tuple[Config, str]:
    db_path = tmp_path / "migration-check.db"
    sync_url = f"sqlite:///{db_path.as_posix()}"
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    return config, sync_url


def test_upgrade_head_creates_the_expected_schema(alembic_config: tuple[Config, str]) -> None:
    config, sync_url = alembic_config

    command.upgrade(config, "head")

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {"users", "workspaces", "projects", "alembic_version"} <= tables

        user_columns = {c["name"] for c in inspector.get_columns("users")}
        assert {"id", "email", "is_active", "created_at", "updated_at"} <= user_columns
    finally:
        engine.dispose()


def test_migration_schema_matches_model_metadata(alembic_config: tuple[Config, str]) -> None:
    config, sync_url = alembic_config

    command.upgrade(config, "head")

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        for table_name, table in Base.metadata.tables.items():
            migrated = {c["name"] for c in inspector.get_columns(table_name)}
            assert {c.name for c in table.columns} == migrated, table_name
    finally:
        engine.dispose()


def test_downgrade_removes_the_schema(alembic_config: tuple[Config, str]) -> None:
    config, sync_url = alembic_config

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(sync_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert not {"users", "workspaces", "projects"} & tables
