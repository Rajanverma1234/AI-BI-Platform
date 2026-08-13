"""Dataset endpoints, nested under a project.

Routes stay thin: they adapt HTTP to the dataset service and back. All file
handling and business logic lives in ``app.services.dataset_service``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import CurrentUser, DbSession, Storage
from app.api.pagination import PageParams
from app.core.exceptions import ValidationError
from app.schemas.common import ErrorResponse
from app.schemas.dataset import DatasetListResponse, DatasetResponse
from app.services import dataset_service

router = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])

#: Read size when streaming an upload to storage.
UPLOAD_CHUNK_SIZE = 1024 * 1024

UploadedFile = Annotated[UploadFile, File(description="CSV or XLSX file")]
DisplayName = Annotated[
    str | None, Form(description="Display name; defaults to the filename")
]

_COMMON_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid token"},
    404: {"model": ErrorResponse, "description": "Project or dataset not accessible"},
}

_UPLOAD_RESPONSES: dict[int | str, dict[str, object]] = {
    **_COMMON_RESPONSES,
    413: {"model": ErrorResponse, "description": "File exceeds the upload limit"},
    415: {"model": ErrorResponse, "description": "Unsupported file type"},
    422: {"model": ErrorResponse, "description": "Empty or malformed file"},
    503: {"model": ErrorResponse, "description": "Storage unavailable"},
}


async def _stream(upload: UploadFile) -> AsyncIterator[bytes]:
    """Yield the upload in chunks so it is never fully buffered in memory."""
    while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
        yield chunk


@router.get(
    "",
    response_model=DatasetListResponse,
    summary="List datasets in a project",
    responses=_COMMON_RESPONSES,
)
async def list_datasets(
    project_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    pagination: PageParams,
) -> DatasetListResponse:
    """Newest first, scoped to a project the caller may access."""
    datasets, total = await dataset_service.list_datasets(
        session, current_user, project_id, pagination
    )
    return DatasetListResponse.build(
        items=[DatasetResponse.model_validate(d) for d in datasets],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a dataset",
    responses=_UPLOAD_RESPONSES,
)
async def upload_dataset(
    project_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    file: UploadedFile,
    name: DisplayName = None,
) -> DatasetResponse:
    """Accept a multipart upload, store it, and extract basic metadata.

    Returns the dataset with its final processing status, so a failed parse is
    reported as `failed` with a safe message rather than as a request error.
    """
    if not file.filename:
        raise ValidationError("A file must be supplied.")

    dataset = await dataset_service.create_dataset(
        session,
        storage,
        current_user,
        project_id,
        filename=file.filename,
        stream=_stream(file),
        name=name,
    )
    return DatasetResponse.model_validate(dataset)


@router.get(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Get a dataset and its metadata",
    responses=_COMMON_RESPONSES,
)
async def get_dataset(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
) -> DatasetResponse:
    dataset = await dataset_service.get_dataset(session, current_user, project_id, dataset_id)
    return DatasetResponse.model_validate(dataset)


@router.put(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Replace a dataset's file (re-upload)",
    responses=_UPLOAD_RESPONSES,
)
async def replace_dataset(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
    file: UploadedFile,
) -> DatasetResponse:
    """Swap the stored file, keeping the dataset id and name."""
    if not file.filename:
        raise ValidationError("A file must be supplied.")

    dataset = await dataset_service.replace_dataset_file(
        session,
        storage,
        current_user,
        project_id,
        dataset_id,
        filename=file.filename,
        stream=_stream(file),
    )
    return DatasetResponse.model_validate(dataset)


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dataset and its stored file",
    responses=_COMMON_RESPONSES,
)
async def delete_dataset(
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    storage: Storage,
) -> None:
    await dataset_service.delete_dataset(session, storage, current_user, project_id, dataset_id)
