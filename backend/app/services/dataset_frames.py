"""Loading dataset files into DataFrames.

Single place where a stored object becomes a DataFrame, so profiling, quality
and cleaning all read a file the same way - and each request reads it once.

Everything here is deterministic: no sampling, no randomness, no LLM.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.core.exceptions import ProcessingError, StorageError
from app.models.dataset import Dataset, DatasetFileType, DatasetStatus
from app.models.dataset_version import DatasetVersion
from app.services.dataset_processing import _detect_csv_delimiter, _detect_csv_encoding
from app.storage.base import StorageProvider


def _resolve_path(storage: StorageProvider, storage_key: str) -> Path:
    path = storage.local_path(storage_key)
    if path is None:
        # A remote provider would need to spill to a temp file first; the local
        # provider always has a path, so this is unreachable today.
        raise StorageError("The configured storage provider cannot be read directly.")
    return Path(path)


def read_frame(
    storage: StorageProvider,
    storage_key: str,
    file_type: DatasetFileType,
) -> pd.DataFrame:
    """Read a stored dataset file into a DataFrame."""
    path = _resolve_path(storage, storage_key)
    if not path.is_file():
        raise StorageError("The stored file is no longer available.")

    try:
        if file_type is DatasetFileType.CSV:
            encoding = _detect_csv_encoding(path)
            delimiter = _detect_csv_delimiter(path, encoding)
            frame = pd.read_csv(path, encoding=encoding, sep=delimiter)
        else:
            frame = pd.read_excel(path, sheet_name=0, engine="openpyxl")
    except ProcessingError:
        raise
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise ProcessingError("The stored file could not be parsed.") from exc

    if frame.columns.empty:
        raise ProcessingError("The dataset has no columns.")
    return frame


def read_dataset_frame(storage: StorageProvider, dataset: Dataset) -> pd.DataFrame:
    """Read the original upload. Never modified by profiling or cleaning."""
    if dataset.status is not DatasetStatus.READY:
        raise ProcessingError(
            "This dataset is not ready yet. Profiling is available once processing succeeds."
        )
    return read_frame(storage, dataset.storage_key, dataset.file_type)


def read_version_frame(storage: StorageProvider, version: DatasetVersion) -> pd.DataFrame:
    """Read a previously produced cleaned version."""
    return read_frame(storage, version.storage_key, version.file_type)


def write_frame(frame: pd.DataFrame, path: Path, file_type: DatasetFileType) -> None:
    """Persist a cleaned frame to a local path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if file_type is DatasetFileType.CSV:
            frame.to_csv(path, index=False)
        else:
            frame.to_excel(path, index=False, engine="openpyxl")
    except (OSError, ValueError) as exc:
        raise StorageError("The cleaned dataset could not be written.") from exc
