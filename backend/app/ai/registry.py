"""Provider registry and selection.

Adding a provider is a two-line change: implement :class:`AIProvider` and
register the factory here. No other module needs to know it exists.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from app.ai.base import AIProvider
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.null_provider import NullProvider
from app.core.config import settings
from app.core.exceptions import ProviderError

ProviderFactory = Callable[[], AIProvider]

_REGISTRY: dict[str, ProviderFactory] = {
    "null": NullProvider,
    "anthropic": AnthropicProvider,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register (or override) a provider factory under ``name``."""
    _REGISTRY[name.lower()] = factory


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def build_provider(name: str) -> AIProvider:
    """Instantiate a provider by name without caching."""
    factory = _REGISTRY.get(name.lower())
    if factory is None:
        raise ProviderError(
            f"Unknown AI provider {name!r}. Available: {', '.join(available_providers())}."
        )
    return factory()


@lru_cache
def get_provider() -> AIProvider:
    """The provider selected by ``AI_PROVIDER``; cached for the process lifetime."""
    return build_provider(settings.AI_PROVIDER)
