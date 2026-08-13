"""Workspace request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from app.schemas.common import ORMModel, Page

#: Lowercase alphanumeric words joined by single hyphens.
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
SLUG_MAX_LENGTH = 100


def normalise_slug(value: object) -> object:
    """Trim and lowercase a slug before it is format-checked.

    Casing and stray whitespace are presentation noise, so they are corrected
    rather than rejected. Anything still outside SLUG_PATTERN (spaces between
    words, punctuation, leading hyphens) is a genuine input error and fails
    validation.
    """
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


#: Shared by workspaces and projects, which use the same slug rules.
Slug = Annotated[
    str,
    BeforeValidator(normalise_slug),
    Field(min_length=1, max_length=SLUG_MAX_LENGTH, pattern=SLUG_PATTERN),
]
Name = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=255)]
Description = Annotated[str, BeforeValidator(_strip), Field(max_length=1000)]


class WorkspaceCreate(BaseModel):
    name: Name
    #: Derived from the name when omitted.
    slug: Slug | None = None
    description: Description | None = None


class WorkspaceUpdate(BaseModel):
    """All fields optional; omitted fields are left unchanged."""

    name: Name | None = None
    slug: Slug | None = None
    description: Description | None = None


class WorkspaceResponse(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


#: Paginated envelope returned by GET /workspaces.
WorkspaceListResponse = Page[WorkspaceResponse]
