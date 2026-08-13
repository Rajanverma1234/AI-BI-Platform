"""Workspace-independent project lookup.

Datasets are addressed as ``/projects/{project_id}/...`` with no workspace in
the path, so the frontend needs a way to resolve a project - and the workspace
to link back to - from the id alone. Authorization still runs through the
owning workspace; only the URL shape differs from the nested project routes,
which remain unchanged.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import ErrorResponse
from app.schemas.project import ProjectResponse
from app.services import dataset_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project by id",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        404: {"model": ErrorResponse, "description": "Project not accessible"},
    },
)
async def get_project(
    project_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> ProjectResponse:
    project = await dataset_service.get_project_for_user(session, current_user, project_id)
    return ProjectResponse.model_validate(project)
