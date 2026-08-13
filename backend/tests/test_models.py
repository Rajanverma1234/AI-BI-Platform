"""Database model, constraint and relationship tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Project, User, Workspace

# password_hash is NOT NULL as of migration 0002; a literal stands in here
# because these tests are about schema constraints, not authentication.
STORED_HASH = "$argon2id$fake-hash-for-model-tests"


async def _seed_workspace(session: AsyncSession) -> Workspace:
    user = User(email="owner@example.test", display_name="Owner", password_hash=STORED_HASH)
    workspace = Workspace(name="Analytics", slug="analytics", owner=user)
    session.add(workspace)
    await session.commit()
    return workspace


async def test_user_gets_uuid_and_timestamps(db_session: AsyncSession) -> None:
    user = User(email="a@example.test", password_hash=STORED_HASH)
    db_session.add(user)
    await db_session.commit()

    assert isinstance(user.id, uuid.UUID)
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.is_active is True
    assert user.is_superuser is False


async def test_user_email_is_unique(db_session: AsyncSession) -> None:
    db_session.add(User(email="dup@example.test", password_hash=STORED_HASH))
    await db_session.commit()

    db_session.add(User(email="dup@example.test", password_hash=STORED_HASH))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_workspace_belongs_to_owner(db_session: AsyncSession) -> None:
    await _seed_workspace(db_session)

    db_session.expunge_all()
    loaded = (
        await db_session.execute(
            select(Workspace)
            .where(Workspace.slug == "analytics")
            .options(selectinload(Workspace.owner).selectinload(User.owned_workspaces))
        )
    ).scalar_one()
    assert loaded.owner.email == "owner@example.test"
    assert loaded.owner.owned_workspaces == [loaded]


async def test_workspace_slug_is_globally_unique(db_session: AsyncSession) -> None:
    workspace = await _seed_workspace(db_session)

    db_session.add(Workspace(name="Copy", slug="analytics", owner_id=workspace.owner_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_project_slug_is_unique_per_workspace(db_session: AsyncSession) -> None:
    workspace = await _seed_workspace(db_session)
    db_session.add(Project(name="Sales", slug="sales", workspace_id=workspace.id))
    await db_session.commit()

    db_session.add(Project(name="Sales again", slug="sales", workspace_id=workspace.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_same_project_slug_allowed_in_other_workspace(db_session: AsyncSession) -> None:
    first = await _seed_workspace(db_session)
    second = Workspace(name="Ops", slug="ops", owner_id=first.owner_id)
    db_session.add(second)
    await db_session.commit()

    db_session.add(Project(name="Sales", slug="sales", workspace_id=first.id))
    db_session.add(Project(name="Sales", slug="sales", workspace_id=second.id))
    await db_session.commit()

    projects = (await db_session.execute(select(Project))).scalars().all()
    assert len(projects) == 2


async def test_expected_tables_and_indexes_exist(db_engine) -> None:
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        workspace_indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("workspaces"))

    assert {"users", "workspaces", "projects"} <= set(tables)
    indexed_columns = {tuple(ix["column_names"]) for ix in workspace_indexes}
    assert ("owner_id",) in indexed_columns
