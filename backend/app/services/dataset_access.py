"""Authorised dataset loading.

One place that turns (user, project_id, dataset_id, version_id) into a
DataFrame, so profiling, cleaning and visualisation all share the same
authorization gate and the same file-reading path.

Every caller goes through ``dataset_service.get_dataset``, which resolves
user -> workspace -> project -> dataset; a version is then scoped to that
already-authorised dataset.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.dataset import Dataset
from app.models.dataset_version import DatasetVersion
from app.models.user import User
from app.services import dataset_frames, dataset_service
from app.storage.base import StorageProvider

VERSION_NOT_FOUND = "Dataset version not found."


@dataclass
class LoadedDataset:
    """A dataset (or one of its versions) resolved to a DataFrame."""

    dataset: Dataset
    frame: pd.DataFrame
    version: DatasetVersion | None = None

    @property
    def version_id(self) -> uuid.UUID | None:
        return self.version.id if self.version else None


async def get_version(
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
        raise NotFoundError(VERSION_NOT_FOUND)
    return version


async def read_source(
    session: AsyncSession,
    storage: StorageProvider,
    dataset: Dataset,
    version_id: uuid.UUID | None,
) -> tuple[pd.DataFrame, DatasetVersion | None]:
    """Read either the original upload or one of its cleaned versions."""
    if version_id is None:
        return dataset_frames.read_dataset_frame(storage, dataset), None

    version = await get_version(session, dataset, version_id)
    return dataset_frames.read_version_frame(storage, version), version


async def load_for_user(
    session: AsyncSession,
    storage: StorageProvider,
    user: User,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> LoadedDataset:
    """Authorise and load in one step. The entry point for read-only features."""
    dataset = await dataset_service.get_dataset(session, user, project_id, dataset_id)
    frame, version = await read_source(session, storage, dataset, version_id)
    return LoadedDataset(dataset=dataset, frame=frame, version=version)
