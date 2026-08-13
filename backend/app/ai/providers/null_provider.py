"""Default no-network provider.

Used in development and tests so the platform boots without credentials.
It never contacts an external service.
"""

from __future__ import annotations

from app.ai.base import AIProvider, CompletionRequest, CompletionResponse, Usage


class NullProvider(AIProvider):
    name = "null"

    def is_configured(self) -> bool:
        return True

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        last_user = next(
            (m.content for m in reversed(list(request.messages)) if m.role == "user"),
            "",
        )
        return CompletionResponse(
            content=f"[null-provider] no AI provider configured; received: {last_user}",
            model=request.model or "null",
            provider=self.name,
            usage=Usage(),
        )
