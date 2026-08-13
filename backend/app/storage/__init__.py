"""Provider-agnostic file storage layer."""

from app.storage.base import StorageProvider, StoredFile, iter_file_chunks
from app.storage.local import LocalStorageProvider
from app.storage.registry import (
    available_providers,
    build_provider,
    get_storage_provider,
    register_provider,
)

__all__ = [
    "LocalStorageProvider",
    "StorageProvider",
    "StoredFile",
    "available_providers",
    "build_provider",
    "get_storage_provider",
    "iter_file_chunks",
    "register_provider",
]
