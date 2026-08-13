"""Anthropic provider.

Talks to the Messages API over plain HTTP so the backend does not take on an
extra SDK dependency at this stage. Credentials come from the environment
(``ANTHROPIC_API_KEY``) and are never written to the repository or logged.
"""

from __future__ import annotations

import httpx

from app.ai.base import AIProvider, CompletionRequest, CompletionResponse, Usage
from app.core.config import settings
from app.core.exceptions import ProviderError

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or settings.ANTHROPIC_API_KEY
        self._model = model or settings.AI_MODEL or DEFAULT_MODEL

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not self.is_configured():
            raise ProviderError("ANTHROPIC_API_KEY is not configured.")

        model = request.model or self._model
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
                if m.role != "system"
            ],
        }
        system = request.system or next(
            (m.content for m in request.messages if m.role == "system"), None
        )
        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=settings.AI_REQUEST_TIMEOUT) as client:
                response = await client.post(
                    API_URL,
                    json=payload,
                    headers={
                        "x-api-key": self._api_key or "",
                        "anthropic-version": API_VERSION,
                        "content-type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"Anthropic request failed with status {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Anthropic request failed.") from exc

        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = data.get("usage", {})
        return CompletionResponse(
            content=text,
            model=data.get("model", model),
            provider=self.name,
            usage=Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
        )
