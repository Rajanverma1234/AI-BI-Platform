"""Dataset business logic: authorization, upload orchestration, lifecycle.

Authorization note: datasets are addressed as
``/projects/{project_id}/datasets/...`` with no workspace in the path, so the
project itself is resolved through a join to the owning workspace. A project id
supplied by the client is never trusted - :func:`get_project_for_user` is the
single gate, and every other function goes through it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    NotFoundError,
    ProcessingError,
    StorageError,
    UnsupportedFileTypeError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.models.dataset import Dataset, DatasetFileType, DatasetStatus
from app.models.project import Project
from app.models.user import User
from app.models.workspace import Workspace
from app.services import dataset_processing
from app.storage.base import StorageProvider

logger = get_logger(__name__)

_PROJECT_NOT_FOUND = "Project not found."
_DATASET_NOT_FOUND = "Dataset not found."

#: Strips directory components and anything awkward out of a client filename.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")


def sanitise_filename(filename: str) -> str:
    """Reduce a client-supplied filename to a safe display value.

    The stored path never uses this - storage keys are generated server-side -
    but it is echoed back to the user, so it must not carry path separators.
    """
    base = Path(filename.replace("\\", "/")).name
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", base).strip(". ")
    return cleaned[:255] or "upload"


def resolve_file_type(filename: str) -> DatasetFileType:
    """Map a filename to a supported type, honouring the configured allow-list."""
    extension = Path(filename).suffix.lower().lstrip(".")
    allowed = {ext.lower() for ext in settings.ALLOWED_DATASET_EXTENSIONS}

    if not extension or extension not in allowed:
        raise UnsupportedFileTypeError(
            f"Unsupported file type. Allowed: {', '.join(sorted(allowed))}."
        )
    try:
        return DatasetFileType(extension)
    except ValueError as exc:
        # Configured but not implemented - a configuration error, not a client one.
        raise UnsupportedFileTypeError("Unsupported file type.") from exc


def build_storage_key(dataset_id: uuid.UUID, file_type: DatasetFileType) -> str:
    """Server-generated key; never derived from client input."""
    return f"datasets/{dataset_id}/source.{file_type.value}"


# --- Authorization -----------------------------------------------------------


async def get_project_for_user(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
) -> Project:
    """Fetch a project the user may access, via its owning workspace.

    Returns 404 rather than 403 for another tenant's project, consistent with
    the workspace and project services.
    """
    result = await session.execute(
        select(Project)
        .join(Workspace, Project.workspace_id == Workspace.id)
        .where(Project.id == project_id, Workspace.owner_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError(_PROJECT_NOT_FOUND)
    return project


async def get_dataset(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
) -> Dataset:
    """Fetch a dataset that belongs to a project the user may access."""
    project = await get_project_for_user(session, user, project_id)
    result = await session.execute(
        select(Dataset).where(
            Dataset.id == dataset_id,
            # Scoping by the authorised project blocks cross-project access.
            Dataset.project_id == project.id,
        )
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise NotFoundError(_DATASET_NOT_FOUND)
    return dataset


# --- Queries -----------------------------------------------------------------


async def list_datasets(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    pagination: Pagination,
) -> tuple[list[Dataset], int]:
    project = await get_project_for_user(session, user, project_id)
    in_project = Dataset.project_id == project.id

    total = await session.scalar(select(func.count()).select_from(Dataset).where(in_project)) or 0

    result = await session.execute(
        select(Dataset)
        .where(in_project)
        .order_by(Dataset.created_at.desc(), Dataset.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    return list(result.scalars().all()), total


# --- Upload pipeline ---------------------------------------------------------


async def _persist(session: AsyncSession, dataset: Dataset) -> None:
    """Flush, then reload the server-maintained columns.

    ``updated_at`` uses an ``onupdate`` default, so an UPDATE leaves it expired.
    Serialising the dataset afterwards would then trigger a lazy load from the
    synchronous response layer and fail with ``MissingGreenlet``. Every exit
    from ``_store_and_process`` goes through here so the failure paths cannot
    drift from the success path again.
    """
    await session.flush()
    await session.refresh(dataset)


async def _store_and_process(
    session: AsyncSession,
    storage: StorageProvider,
    dataset: Dataset,
    stream: AsyncIterator[bytes],
) -> Dataset:
    """Store the file, extract metadata, and move the dataset to its end state.

    Any failure marks the dataset ``failed`` with a safe message - it is never
    left as ``ready`` after an error.
    """
    try:
        stored = await storage.upload(
            dataset.storage_key,
            stream,
            max_bytes=settings.max_upload_size_bytes,
        )
    except Exception:
        # Storage failures propagate: there is nothing worth keeping.
        await session.delete(dataset)
        await session.flush()
        raise

    if stored.size_bytes == 0:
        await storage.delete(dataset.storage_key)
        await session.delete(dataset)
        await session.flush()
        raise ValidationError("The uploaded file is empty.")

    dataset.file_size = stored.size_bytes
    dataset.status = DatasetStatus.PROCESSING
    dataset.error_message = None
    session.add(dataset)
    await session.flush()

    path = storage.local_path(dataset.storage_key)
    if path is None:
        # A remote provider would need a temporary spill file; the local
        # provider always has a path, so this is unreachable today.
        raise StorageError("The configured storage provider cannot be read for processing.")

    try:
        metadata = dataset_processing.extract_metadata(Path(path), dataset.file_type)
    except ProcessingError as exc:
        dataset.status = DatasetStatus.FAILED
        dataset.error_message = exc.message
        session.add(dataset)
        await _persist(session, dataset)
        logger.info(
            "Dataset processing failed", extra={"dataset_id": str(dataset.id), "reason": exc.code}
        )
        return dataset
    except Exception:
        dataset.status = DatasetStatus.FAILED
        dataset.error_message = "The file could not be processed."
        session.add(dataset)
        await _persist(session, dataset)
        logger.exception(
            "Unexpected dataset processing error", extra={"dataset_id": str(dataset.id)}
        )
        return dataset

    dataset.row_count = metadata.row_count
    dataset.column_count = metadata.column_count
    dataset.columns = metadata.columns_as_dicts()
    dataset.status = DatasetStatus.READY
    dataset.error_message = None
    session.add(dataset)
    await _persist(session, dataset)
    return dataset


async def create_dataset(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    *,
    filename: str,
    stream: AsyncIterator[bytes],
    name: str | None = None,
) -> Dataset:
    """Upload a file and register it as a dataset of ``project_id``."""
    project = await get_project_for_user(session, user, project_id)

    safe_filename = sanitise_filename(filename)
    file_type = resolve_file_type(safe_filename)

    dataset = Dataset(
        project_id=project.id,
        name=(name or Path(safe_filename).stem or safe_filename)[:255],
        original_filename=safe_filename,
        file_type=file_type,
        status=DatasetStatus.UPLOADING,
        file_size=0,
        storage_key="",
    )
    session.add(dataset)
    # Flush to obtain the id the storage key is built from.
    await session.flush()
    dataset.storage_key = build_storage_key(dataset.id, file_type)
    session.add(dataset)
    await session.flush()

    return await _store_and_process(session, storage, dataset, stream)


async def replace_dataset_file(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    *,
    filename: str,
    stream: AsyncIterator[bytes],
) -> Dataset:
    """Re-upload a dataset's file in place, keeping its id and name."""
    dataset = await get_dataset(session, user, project_id, dataset_id)

    safe_filename = sanitise_filename(filename)
    file_type = resolve_file_type(safe_filename)

    previous_key = dataset.storage_key
    dataset.original_filename = safe_filename
    dataset.file_type = file_type
    dataset.storage_key = build_storage_key(dataset.id, file_type)
    dataset.status = DatasetStatus.UPLOADING
    # Clear stale metadata so a failed replace cannot show the old numbers.
    dataset.row_count = None
    dataset.column_count = None
    dataset.columns = None
    dataset.error_message = None
    session.add(dataset)
    await session.flush()

    updated = await _store_and_process(session, storage, dataset, stream)

    if previous_key and previous_key != updated.storage_key:
        # Only drop the old object once the new one is safely in place.
        await storage.delete(previous_key)

    return updated


async def delete_dataset(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
) -> None:
    """Delete the row and its stored file."""
    dataset = await get_dataset(session, user, project_id, dataset_id)
    storage_key = dataset.storage_key

    await session.delete(dataset)
    await session.flush()

    if storage_key:
        # A leftover object is recoverable; a dangling row is not, so the file
        # is removed only after the row is gone.
        await storage.delete(storage_key)
