"""Default no-network provider.

Used in development and tests so the platform boots without credentials.
It never contacts an external service.

It reports itself as **not configured**, which is what it is: a stub standing
in for an AI provider that has not been set up. Every AI call site checks
``is_configured()`` and takes a deterministic fallback when it is false, so
this is what makes the platform degrade honestly instead of presenting an
empty - or worse, a stub - answer as though a model had produced it.
"""

from __future__ import annotations

from app.ai.base import AIProvider, CompletionRequest, CompletionResponse, Usage


class NullProvider(AIProvider):
    name = "null"

    def is_configured(self) -> bool:
        # Not "is this provider usable" but "is an AI actually available".
        # The stub has no model behind it, so the answer is no.
        return False

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Echo the prompt back.

        Only reached if a caller skips the ``is_configured()`` check; the
        content is deliberately self-identifying so such a call is obvious.
        """
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
