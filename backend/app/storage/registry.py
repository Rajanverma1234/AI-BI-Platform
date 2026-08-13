"""Storage provider registry and selection.

Adding a provider (e.g. S3) is a two-line change: implement
:class:`StorageProvider` and register the factory here.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from app.core.config import settings
from app.core.exceptions import StorageError
from app.storage.base import StorageProvider
from app.storage.local import LocalStorageProvider

ProviderFactory = Callable[[], StorageProvider]

_REGISTRY: dict[str, ProviderFactory] = {
    "local": LocalStorageProvider,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register (or override) a storage provider factory under ``name``."""
    _REGISTRY[name.lower()] = factory


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def build_provider(name: str) -> StorageProvider:
    factory = _REGISTRY.get(name.lower())
    if factory is None:
        raise StorageError(
            f"Unknown storage provider {name!r}. Available: {', '.join(available_providers())}."
        )
    return factory()


@lru_cache
def get_storage_provider() -> StorageProvider:
    """The provider selected by ``STORAGE_PROVIDER``, cached per process."""
    return build_provider(settings.STORAGE_PROVIDER)
