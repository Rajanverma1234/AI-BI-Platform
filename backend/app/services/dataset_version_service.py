"""Profiling, quality and cleaning orchestration.

Ties the authorization gate, the storage layer and the deterministic
profiling/quality/cleaning services together.

Original-data protection: nothing here ever writes to ``dataset.storage_key``.
Applying a pipeline always writes a new object and inserts a new
``dataset_versions`` row.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, StorageError, ValidationError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.models.dataset import Dataset
from app.models.dataset_version import DatasetVersion
from app.models.user import User
from app.schemas.cleaning import (
    CleaningApplyRequest,
    CleaningOperation,
    CleaningPreviewResponse,
    OperationOutcome,
    TypeChange,
)
from app.schemas.profiling import DataQualitySummary, DatasetProfile
from app.services import (
    data_quality,
    dataset_cleaning,
    dataset_frames,
    dataset_profiling,
    dataset_service,
)
from app.storage.base import StorageProvider

logger = get_logger(__name__)

#: Rows returned in a preview sample - display only, never the whole result.
PREVIEW_SAMPLE_ROWS = 20

_VERSION_NOT_FOUND = "Dataset version not found."


async def _get_version(
    session: AsyncSession,
    dataset: Dataset,
    version_id: uuid.UUID,
) -> DatasetVersion:
    """Load a version, scoped to an already-authorised dataset."""
    result = await session.execute(
        select(DatasetVersion).where(
            DatasetVersion.id == version_id,
            # Scoping by dataset prevents reaching another tenant's version.
            DatasetVersion.dataset_id == dataset.id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise NotFoundError(_VERSION_NOT_FOUND)
    return version


async def _load_source(
    session: AsyncSession,
    storage: StorageProvider,
    dataset: Dataset,
    source_version_id: uuid.UUID | None,
) -> tuple[pd.DataFrame, DatasetVersion | None]:
    """Read either the original upload or a prior cleaned version."""
    if source_version_id is None:
        return dataset_frames.read_dataset_frame(storage, dataset), None

    version = await _get_version(session, dataset, source_version_id)
    return dataset_frames.read_version_frame(storage, version), version


# --- Profiling and quality ---------------------------------------------------


async def profile_dataset(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> DatasetProfile:
    dataset = await dataset_service.get_dataset(session, user, project_id, dataset_id)
    frame, version = await _load_source(session, storage, dataset, version_id)
    return dataset_profiling.profile_frame(
        frame, dataset_id=dataset.id, version_id=version.id if version else None
    )


async def assess_dataset_quality(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> DataQualitySummary:
    dataset = await dataset_service.get_dataset(session, user, project_id, dataset_id)
    frame, version = await _load_source(session, storage, dataset, version_id)
    # One read, reused for both the profile and the rules that depend on it.
    profile = dataset_profiling.profile_frame(
        frame, dataset_id=dataset.id, version_id=version.id if version else None
    )
    return data_quality.assess_quality(
        profile, frame, dataset_id=dataset.id, version_id=version.id if version else None
    )


# --- Cleaning ----------------------------------------------------------------


def _json_safe(value: object) -> object:
    """Make a cell safe for JSON: NaN/NaT become None, others become strings."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if pd.isna(value):
        return None
    return str(value)


def _build_preview(
    dataset: Dataset,
    source_version: DatasetVersion | None,
    before: pd.DataFrame,
    after: pd.DataFrame,
    outcomes: list[OperationOutcome],
    warnings: list[str],
) -> CleaningPreviewResponse:
    """Compare the before/after frames into a user-facing preview."""
    before_types = {
        str(name): dataset_profiling.detect_type(before[name]) for name in before.columns
    }
    after_types = {
        str(name): dataset_profiling.detect_type(after[name]) for name in after.columns
    }

    type_changes = [
        TypeChange(column=name, before=before_types[name], after=after_types[name])
        for name in after_types
        if name in before_types and before_types[name] != after_types[name]
    ]

    # Columns touched by an operation, plus any added/removed/retyped ones.
    affected = {
        outcome.column for outcome in outcomes if outcome.column
    } | {change.column for change in type_changes}
    affected |= set(before_types) ^ set(after_types)

    sample = after.head(PREVIEW_SAMPLE_ROWS)
    sample_rows = [
        {str(column): _json_safe(row[column]) for column in sample.columns}
        for _, row in sample.iterrows()
    ]

    return CleaningPreviewResponse(
        dataset_id=dataset.id,
        source_version_id=source_version.id if source_version else None,
        original_row_count=int(len(before)),
        cleaned_row_count=int(len(after)),
        original_column_count=int(len(before.columns)),
        cleaned_column_count=int(len(after.columns)),
        missing_cells_before=int(before.isna().sum().sum()),
        missing_cells_after=int(after.isna().sum().sum()),
        duplicate_rows_before=int(before.duplicated().sum()),
        duplicate_rows_after=int(after.duplicated().sum()),
        rows_removed=max(int(len(before) - len(after)), 0),
        affected_columns=sorted(affected),
        type_changes=type_changes,
        operations=outcomes,
        warnings=warnings,
        sample_rows=sample_rows,
    )


async def preview_cleaning(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    operations: list[CleaningOperation],
    source_version_id: uuid.UUID | None = None,
) -> CleaningPreviewResponse:
    """Run the pipeline in memory and report the effect. Nothing is persisted."""
    dataset = await dataset_service.get_dataset(session, user, project_id, dataset_id)
    before, source_version = await _load_source(session, storage, dataset, source_version_id)

    after, outcomes, warnings = dataset_cleaning.run_pipeline(before, operations)
    return _build_preview(dataset, source_version, before, after, outcomes, warnings)


async def _next_version_number(session: AsyncSession, dataset_id: uuid.UUID) -> int:
    highest = await session.scalar(
        select(func.max(DatasetVersion.version_number)).where(
            DatasetVersion.dataset_id == dataset_id
        )
    )
    return int(highest or 0) + 1


async def apply_cleaning(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: CleaningApplyRequest,
) -> tuple[DatasetVersion, CleaningPreviewResponse]:
    """Run the pipeline and persist the result as a new version.

    The original dataset row and file are left untouched.
    """
    dataset = await dataset_service.get_dataset(session, user, project_id, dataset_id)
    before, source_version = await _load_source(
        session, storage, dataset, payload.source_version_id
    )

    after, outcomes, warnings = dataset_cleaning.run_pipeline(before, payload.operations)
    if after.columns.empty:
        raise ValidationError("The cleaning pipeline removed every column.")

    preview = _build_preview(dataset, source_version, before, after, outcomes, warnings)

    version_number = await _next_version_number(session, dataset.id)
    version = DatasetVersion(
        dataset_id=dataset.id,
        source_version_id=source_version.id if source_version else None,
        version_number=version_number,
        name=payload.name or f"{dataset.name} (cleaned v{version_number})",
        storage_key="",
        file_type=dataset.file_type,
        file_size=0,
        row_count=int(len(after)),
        column_count=int(len(after.columns)),
        columns=[
            {
                "name": str(name),
                "dtype": dataset_profiling.detect_type(after[name]).value,
                "nullable": bool(after[name].isna().any()),
            }
            for name in after.columns
        ],
        operations=[operation.model_dump(mode="json") for operation in payload.operations],
    )
    session.add(version)
    # Flush to obtain the id the storage key is derived from.
    await session.flush()

    version.storage_key = (
        f"datasets/{dataset.id}/versions/{version.id}/data.{dataset.file_type.value}"
    )

    local_path = storage.local_path(version.storage_key)
    if local_path is None:
        raise StorageError("The configured storage provider cannot be written directly.")

    target = Path(local_path)
    dataset_frames.write_frame(after, target, dataset.file_type)
    version.file_size = int(target.stat().st_size) if target.is_file() else 0

    session.add(version)
    await session.flush()
    await session.refresh(version)

    logger.info(
        "Created cleaned dataset version",
        extra={
            "dataset_id": str(dataset.id),
            "version_id": str(version.id),
            "version_number": version_number,
            "operations": len(payload.operations),
        },
    )
    return version, preview


async def list_versions(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    pagination: Pagination,
) -> tuple[list[DatasetVersion], int]:
    dataset = await dataset_service.get_dataset(session, user, project_id, dataset_id)
    belongs = DatasetVersion.dataset_id == dataset.id

    total = (
        await session.scalar(select(func.count()).select_from(DatasetVersion).where(belongs)) or 0
    )
    result = await session.execute(
        select(DatasetVersion)
        .where(belongs)
        .order_by(DatasetVersion.version_number.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    return list(result.scalars().all()), total
