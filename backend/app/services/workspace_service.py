"""Workspace business logic, including the tenancy boundary.

Membership is ownership in the current schema: a workspace belongs to exactly
one user via ``owner_id``. Every read and write goes through
:func:`get_workspace_for_user`, so a workspace the caller does not own is
indistinguishable from one that does not exist.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.pagination import Pagination
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate
from app.utils.slug import resolve_slug

_NOT_FOUND = "Workspace not found."


async def list_workspaces(
    session: AsyncSession,
    user: User,
    pagination: Pagination,
) -> tuple[list[Workspace], int]:
    """Return one page of the caller's workspaces and the total count."""
    owned = Workspace.owner_id == user.id

    total = await session.scalar(select(func.count()).select_from(Workspace).where(owned)) or 0

    result = await session.execute(
        select(Workspace)
        .where(owned)
        # Newest first, with id as a tiebreaker so paging is deterministic.
        .order_by(Workspace.created_at.desc(), Workspace.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    return list(result.scalars().all()), total


async def get_workspace_for_user(
    session: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
) -> Workspace:
    """Fetch a workspace the user may access.

    Raises :class:`NotFoundError` both when the workspace does not exist and
    when it belongs to someone else - returning 403 instead would confirm the
    id is real to an attacker probing for other tenants' workspaces.
    """
    result = await session.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == user.id,
        )
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise NotFoundError(_NOT_FOUND)
    return workspace


async def create_workspace(
    session: AsyncSession,
    user: User,
    payload: WorkspaceCreate,
) -> Workspace:
    """Create a workspace owned by ``user``."""
    workspace = Workspace(
        name=payload.name,
        slug=resolve_slug(payload.slug, payload.name),
        description=payload.description,
        owner_id=user.id,
    )
    session.add(workspace)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A workspace with this slug already exists.") from exc
    return workspace


async def update_workspace(
    session: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
) -> Workspace:
    workspace = await get_workspace_for_user(session, user, workspace_id)

    # exclude_unset keeps an omitted field different from an explicit null.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(workspace, field, value)

    session.add(workspace)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("A workspace with this slug already exists.") from exc

    # UPDATE does not use RETURNING, so the onupdate `updated_at` is expired;
    # refresh explicitly rather than let the response trigger lazy async IO.
    await session.refresh(workspace)
    return workspace


async def delete_workspace(session: AsyncSession, user: User, workspace_id: uuid.UUID) -> None:
    """Delete a workspace and, by cascade, its projects."""
    workspace = await get_workspace_for_user(session, user, workspace_id)
    await session.delete(workspace)
    await session.flush()
