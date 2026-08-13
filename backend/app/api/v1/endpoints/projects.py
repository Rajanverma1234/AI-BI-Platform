"""Project endpoints, nested under a workspace.

The workspace id in the path is always authorised first, so a project can only
be reached through the workspace that owns it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import PageParams
from app.schemas.common import ErrorResponse
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services import project_service

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["projects"])

_AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Workspace or project not accessible"},
}


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project in a workspace",
    responses={
        **_AUTH_RESPONSES,
        409: {"model": ErrorResponse, "description": "Slug already used in this workspace"},
    },
)
async def create_project(
    workspace_id: uuid.UUID,
    payload: ProjectCreate,
    session: DbSession,
    current_user: CurrentUser,
) -> ProjectResponse:
    project = await project_service.create_project(session, current_user, workspace_id, payload)
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects in a workspace",
    responses=_AUTH_RESPONSES,
)
async def list_projects(
    workspace_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    pagination: PageParams,
) -> ProjectListResponse:
    """Newest first, scoped to a workspace the caller owns."""
    projects, total = await project_service.list_projects(
        session, current_user, workspace_id, pagination
    )
    return ProjectListResponse.build(
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project",
    responses=_AUTH_RESPONSES,
)
async def get_project(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> ProjectResponse:
    project = await project_service.get_project(session, current_user, workspace_id, project_id)
    return ProjectResponse.model_validate(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project",
    responses={
        **_AUTH_RESPONSES,
        409: {"model": ErrorResponse, "description": "Slug already used in this workspace"},
    },
)
async def update_project(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    session: DbSession,
    current_user: CurrentUser,
) -> ProjectResponse:
    project = await project_service.update_project(
        session, current_user, workspace_id, project_id, payload
    )
    return ProjectResponse.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
    responses=_AUTH_RESPONSES,
)
async def delete_project(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> None:
    await project_service.delete_project(session, current_user, workspace_id, project_id)
