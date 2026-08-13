"""Dataset request/response schemas.

``storage_key`` is deliberately absent from every response: it is an internal
storage locator and must not leak to clients.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.dataset import DatasetFileType, DatasetStatus
from app.schemas.common import ORMModel, Page
from app.schemas.workspace import Description, Name


class DatasetColumn(BaseModel):
    """One column detected while processing the file."""

    name: str
    #: Normalised type label: integer | float | boolean | datetime | string.
    dtype: str
    nullable: bool = False


class DatasetMetadataResponse(BaseModel):
    """Structural summary extracted from an uploaded file."""

    original_filename: str
    file_type: DatasetFileType
    file_size: int = Field(ge=0)
    row_count: int | None = None
    column_count: int | None = None
    columns: list[DatasetColumn] = Field(default_factory=list)


class DatasetResponse(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    original_filename: str
    file_type: DatasetFileType
    file_size: int
    status: DatasetStatus
    row_count: int | None = None
    column_count: int | None = None
    columns: list[DatasetColumn] | None = None
    #: Safe, user-facing failure reason; set only when status is "failed".
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


#: Paginated envelope returned by GET .../datasets.
DatasetListResponse = Page[DatasetResponse]


class DatasetUpdate(BaseModel):
    """Rename or re-describe a dataset without touching the stored file."""

    name: Name | None = None
    description: Description | None = None
