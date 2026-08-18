"""AI provider abstraction tests.

These must never make a network call.
"""

from __future__ import annotations

import pytest

from app.ai import (
    AIProvider,
    CompletionRequest,
    CompletionResponse,
    Message,
    available_providers,
    build_provider,
    register_provider,
)
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.null_provider import NullProvider
from app.core.exceptions import ProviderError


async def test_null_provider_is_the_safe_default() -> None:
    provider = build_provider("null")

    assert isinstance(provider, NullProvider)


async def test_null_provider_reports_itself_as_not_configured() -> None:
    """Regression: it used to claim it was configured.

    Every AI call site branches on ``is_configured()`` and falls back to
    deterministic output when it is false. While the stub claimed to be
    configured those branches were skipped, so callers ran the stub and
    presented its echo as a real answer - the NLQ endpoint returned
    "[null-provider] no AI provider configured; received: {...}" to the user,
    and the analyst reported ai_available=True with an empty narrative.
    """
    assert NullProvider().is_configured() is False


async def test_null_provider_completes_without_network() -> None:
    provider = NullProvider()

    result = await provider.complete(
        CompletionRequest(messages=[Message(role="user", content="revenue by month")])
    )

    assert isinstance(result, CompletionResponse)
    assert result.provider == "null"
    assert "revenue by month" in result.content


async def test_stream_falls_back_to_a_single_chunk() -> None:
    provider = NullProvider()
    request = CompletionRequest(messages=[Message(role="user", content="hi")])

    chunks = [chunk async for chunk in provider.stream(request)]

    assert len(chunks) == 1
    assert chunks[0]


def test_unknown_provider_raises_provider_error() -> None:
    with pytest.raises(ProviderError, match="Unknown AI provider"):
        build_provider("does-not-exist")


def test_registry_lists_built_in_providers() -> None:
    assert {"null", "anthropic"} <= set(available_providers())


def test_new_providers_can_be_registered_without_touching_callers() -> None:
    class StubProvider(AIProvider):
        name = "stub"

        def is_configured(self) -> bool:
            return True

        async def complete(self, request: CompletionRequest) -> CompletionResponse:
            return CompletionResponse(content="stub", model="stub", provider=self.name)

    register_provider("stub", StubProvider)

    assert isinstance(build_provider("stub"), StubProvider)


def test_anthropic_provider_reports_unconfigured_without_a_key() -> None:
    assert AnthropicProvider(api_key=None).is_configured() is False
    assert AnthropicProvider(api_key="test-key").is_configured() is True


async def test_anthropic_provider_refuses_to_call_without_a_key() -> None:
    provider = AnthropicProvider(api_key=None)

    with pytest.raises(ProviderError, match="not configured"):
        await provider.complete(
            CompletionRequest(messages=[Message(role="user", content="hi")])
        )
