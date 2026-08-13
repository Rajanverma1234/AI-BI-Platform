"""Provider-agnostic file storage interface.

Dataset business logic depends only on :class:`StorageProvider`. Concrete
providers are registered in ``app.storage.registry`` and selected with the
``STORAGE_PROVIDER`` environment variable, mirroring how ``app.ai`` handles AI
providers. Adding S3 later means adding one module - no service changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import BinaryIO


@dataclass(frozen=True)
class StoredFile:
    """Result of a completed upload."""

    #: Provider-scoped identifier, e.g. "datasets/<uuid>/data.csv".
    storage_key: str
    size_bytes: int


class StorageProvider(ABC):
    """Contract every storage backend must satisfy."""

    #: Stable identifier used by ``STORAGE_PROVIDER`` and in logs.
    name: str = "base"

    @abstractmethod
    async def upload(
        self,
        storage_key: str,
        stream: AsyncIterator[bytes],
        *,
        max_bytes: int | None = None,
    ) -> StoredFile:
        """Persist ``stream`` under ``storage_key``.

        Implementations must write incrementally rather than buffering the
        whole file, and must raise
        :class:`app.core.exceptions.FileTooLargeError` as soon as ``max_bytes``
        is exceeded, leaving no partial object behind.
        """

    @abstractmethod
    def open(self, storage_key: str) -> AbstractContextManager[BinaryIO]:
        """Open the stored object for binary reading."""

    @abstractmethod
    async def delete(self, storage_key: str) -> None:
        """Remove the object. Deleting a missing object is not an error."""

    @abstractmethod
    async def exists(self, storage_key: str) -> bool:
        """True when the object is present."""

    @abstractmethod
    def local_path(self, storage_key: str) -> str | None:
        """Filesystem path, when the provider has one.

        Parsers use this to read a file in place. Providers without local
        files (S3) return ``None`` and callers fall back to :meth:`open`.
        """


async def iter_file_chunks(source: BinaryIO, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    """Adapt a synchronous binary file object to the async upload stream."""
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break
        yield chunk


def chunks_of(data: bytes, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Split an in-memory buffer into chunks (used by tests and small writes)."""
    for start in range(0, len(data), chunk_size):
        yield data[start : start + chunk_size]
