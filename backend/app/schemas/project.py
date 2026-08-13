"""Project request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel, Page
from app.schemas.workspace import Description, Name, Slug


class ProjectCreate(BaseModel):
    name: Name
    #: Derived from the name when omitted. Unique within the workspace.
    slug: Slug | None = None
    description: Description | None = None


class ProjectUpdate(BaseModel):
    """All fields optional; omitted fields are left unchanged."""

    name: Name | None = None
    slug: Slug | None = None
    description: Description | None = None


class ProjectResponse(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    workspace_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


#: Paginated envelope returned by GET /workspaces/{id}/projects.
ProjectListResponse = Page[ProjectResponse]
