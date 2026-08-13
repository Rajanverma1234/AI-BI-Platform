"""Local filesystem storage provider (development default)."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings
from app.core.exceptions import FileTooLargeError, StorageError
from app.core.logging import get_logger
from app.storage.base import StorageProvider, StoredFile

logger = get_logger(__name__)


class LocalStorageProvider(StorageProvider):
    """Stores objects under a configurable root directory."""

    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root or settings.STORAGE_LOCAL_ROOT).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, storage_key: str) -> Path:
        """Map a key to a path, refusing anything that escapes the root.

        Keys are generated server-side, but this is cheap insurance against a
        traversal bug ever reaching the filesystem.
        """
        candidate = (self._root / storage_key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageError("Invalid storage key.")
        return candidate

    async def upload(
        self,
        storage_key: str,
        stream: AsyncIterator[bytes],
        *,
        max_bytes: int | None = None,
    ) -> StoredFile:
        target = self._resolve(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        try:
            with target.open("wb") as handle:
                async for chunk in stream:
                    written += len(chunk)
                    if max_bytes is not None and written > max_bytes:
                        # Abort before the oversized file is fully persisted.
                        handle.close()
                        target.unlink(missing_ok=True)
                        raise FileTooLargeError(
                            f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB upload limit."
                        )
                    await asyncio.to_thread(handle.write, chunk)
        except FileTooLargeError:
            raise
        except OSError as exc:
            target.unlink(missing_ok=True)
            logger.exception("Local storage write failed for %s", storage_key)
            raise StorageError("Could not store the uploaded file.") from exc

        return StoredFile(storage_key=storage_key, size_bytes=written)

    @contextmanager
    def open(self, storage_key: str) -> Iterator[BinaryIO]:
        path = self._resolve(storage_key)
        try:
            handle = path.open("rb")
        except OSError as exc:
            raise StorageError("Stored file could not be read.") from exc
        try:
            yield handle
        finally:
            handle.close()

    async def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        try:
            await asyncio.to_thread(path.unlink, True)
            # Tidy up the per-dataset directory when it becomes empty.
            parent = path.parent
            if parent != self._root and parent.is_dir() and not any(parent.iterdir()):
                await asyncio.to_thread(shutil.rmtree, parent, True)
        except OSError as exc:
            logger.warning("Local storage delete failed for %s: %s", storage_key, exc)

    async def exists(self, storage_key: str) -> bool:
        return await asyncio.to_thread(self._resolve(storage_key).is_file)

    def local_path(self, storage_key: str) -> str | None:
        return str(self._resolve(storage_key))
