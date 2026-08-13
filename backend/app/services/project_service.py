"""Project business logic.

Every function first resolves the parent workspace through
``workspace_service.get_workspace_for_user``, so a caller can never reach a
project in a workspace they do not own, and a project id from another
workspace cannot be smuggled into a request path.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.pagination import Pagination
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.workspace_service import get_workspace_for_user
from app.utils.slug import resolve_slug

_NOT_FOUND = "Project not found."


async def list_projects(
    session: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    pagination: Pagination,
) -> tuple[list[Project], int]:
    """Return one page of a workspace's projects and the total count."""
    # Authorise the workspace first; an inaccessible one never reaches the query.
    workspace = await get_workspace_for_user(session, user, workspace_id)
    in_workspace = Project.workspace_id == workspace.id

    total = (
        await session.scalar(select(func.count()).select_from(Project).where(in_workspace)) or 0
    )

    result = await session.execute(
        select(Project)
        .where(in_workspace)
        .order_by(Project.created_at.desc(), Project.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    return list(result.scalars().all()), total


async def get_project(
    session: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> Project:
    """Fetch a project that belongs to a workspace the user owns."""
    workspace = await get_workspace_for_user(session, user, workspace_id)
    result = await session.execute(
        select(Project).where(
            Project.id == project_id,
            # Scoping by workspace is what blocks cross-workspace access.
            Project.workspace_id == workspace.id,
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError(_NOT_FOUND)
    return project


async def create_project(
    session: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    payload: ProjectCreate,
) -> Project:
    workspace = await get_workspace_for_user(session, user, workspace_id)
    project = Project(
        name=payload.name,
        slug=resolve_slug(payload.slug, payload.name),
        description=payload.description,
        workspace_id=workspace.id,
    )
    session.add(project)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A project with this slug already exists in this workspace.") from exc
    return project


async def update_project(
    session: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: ProjectUpdate,
) -> Project:
    project = await get_project(session, user, workspace_id, project_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    session.add(project)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A project with this slug already exists in this workspace.") from exc

    # UPDATE does not use RETURNING, so the onupdate `updated_at` is expired;
    # refresh explicitly rather than let the response trigger lazy async IO.
    await session.refresh(project)
    return project


async def delete_project(
    session: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    project = await get_project(session, user, workspace_id, project_id)
    await session.delete(project)
    await session.flush()
