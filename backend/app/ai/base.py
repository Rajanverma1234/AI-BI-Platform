"""Provider-agnostic AI interface.

Application code depends only on :class:`AIProvider`; concrete providers
(Anthropic, OpenAI, a local model, ...) are registered in ``app.ai.registry``
and selected via the ``AI_PROVIDER`` environment variable. Nothing outside
``app/ai`` should import a provider module directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class Message(BaseModel):
    role: Role
    content: str


class CompletionRequest(BaseModel):
    messages: Sequence[Message]
    model: str | None = None
    max_tokens: int = Field(default=1024, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    system: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class CompletionResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: Usage = Field(default_factory=Usage)


class AIProvider(ABC):
    """Minimal contract every provider must satisfy."""

    #: Stable identifier used by ``AI_PROVIDER`` and in logs.
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """True when the provider has everything it needs to make a call."""

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Run a single completion."""

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        """Stream a completion. Providers without streaming fall back to one chunk."""
        response = await self.complete(request)
        yield response.content
