"""Workspace endpoints. Every route requires authentication."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParams
from app.schemas.common import ErrorResponse
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Workspace not found or not accessible"},
}


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        409: {"model": ErrorResponse, "description": "Slug already taken"},
    },
)
async def create_workspace(
    payload: WorkspaceCreate,
    session: DbSession,
    current_user: CurrentUser,
) -> WorkspaceResponse:
    """Create a workspace owned by the authenticated user."""
    workspace = await workspace_service.create_workspace(session, current_user, payload)
    return WorkspaceResponse.model_validate(workspace)


@router.get(
    "",
    response_model=WorkspaceListResponse,
    summary="List the caller's workspaces",
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid token"}},
)
async def list_workspaces(
    session: DbSession,
    current_user: CurrentUser,
    pagination: PageParams,
) -> WorkspaceListResponse:
    """Newest first. Only workspaces owned by the caller are returned."""
    workspaces, total = await workspace_service.list_workspaces(session, current_user, pagination)
    return WorkspaceListResponse.build(
        items=[WorkspaceResponse.model_validate(w) for w in workspaces],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Get a workspace",
    responses=_AUTH_RESPONSES,
)
async def get_workspace(
    workspace_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> WorkspaceResponse:
    workspace = await workspace_service.get_workspace_for_user(session, current_user, workspace_id)
    return WorkspaceResponse.model_validate(workspace)


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Update a workspace",
    responses={
        **_AUTH_RESPONSES,
        409: {"model": ErrorResponse, "description": "Slug already taken"},
    },
)
async def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
    session: DbSession,
    current_user: CurrentUser,
) -> WorkspaceResponse:
    workspace = await workspace_service.update_workspace(
        session, current_user, workspace_id, payload
    )
    return WorkspaceResponse.model_validate(workspace)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workspace and its projects",
    responses=_AUTH_RESPONSES,
)
async def delete_workspace(
    workspace_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> None:
    await workspace_service.delete_workspace(session, current_user, workspace_id)
