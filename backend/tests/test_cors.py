"""CORS behaviour for deployed frontends.

The deployment that prompted these tests failed like this: the browser sent a
preflight from a Vercel *preview* origin, which was not in CORS_ORIGINS, so
Starlette answered ``400 Bad Request`` with no Access-Control-Allow-Origin
header and Chrome reported the fetch as a plain network error. Nothing in the
API logs looked wrong, and the frontend surfaced it as "Could not reach the
API. Is the backend running?".

CORS_ORIGIN_REGEX exists for those origins. These tests pin both halves of the
contract: a matching preview origin is allowed, and an unrelated origin is
still refused.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import config as config_module
from app.main import create_app

PRODUCTION_ORIGIN = "https://ai-bi-platform-sepia.vercel.app"
PREVIEW_ORIGIN = "https://ai-bi-platform-2th2yqbdj-rajanverma1234s-projects.vercel.app"
# Matches "<project>-<build hash>-<team>.vercel.app" and nothing else.
PREVIEW_REGEX = r"^https://ai-bi-platform-[a-z0-9]+-rajanverma1234s-projects\.vercel\.app$"


@pytest.fixture
def cors_client(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    """A client for an app configured the way the Render service should be."""
    monkeypatch.setattr(config_module.settings, "CORS_ORIGINS", [PRODUCTION_ORIGIN])
    monkeypatch.setattr(config_module.settings, "CORS_ORIGIN_REGEX", PREVIEW_REGEX)
    transport = ASGITransport(app=create_app())
    return AsyncClient(transport=transport, base_url="https://api.test")


async def _preflight(client: AsyncClient, origin: str):
    return await client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


async def test_preflight_allows_the_production_origin(cors_client: AsyncClient) -> None:
    async with cors_client as client:
        response = await _preflight(client, PRODUCTION_ORIGIN)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PRODUCTION_ORIGIN


async def test_preflight_allows_a_matching_preview_origin(cors_client: AsyncClient) -> None:
    """The regression: without CORS_ORIGIN_REGEX this is a 400 with no header."""
    async with cors_client as client:
        response = await _preflight(client, PREVIEW_ORIGIN)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PREVIEW_ORIGIN


async def test_preflight_still_refuses_an_unrelated_origin(cors_client: AsyncClient) -> None:
    async with cors_client as client:
        response = await _preflight(client, "https://attacker.example")

    assert "access-control-allow-origin" not in response.headers


async def test_preflight_refuses_a_lookalike_vercel_origin(cors_client: AsyncClient) -> None:
    """Anyone can deploy to *.vercel.app, so the pattern must not end there."""
    async with cors_client as client:
        response = await _preflight(client, "https://ai-bi-platform-evil.vercel.app")

    assert "access-control-allow-origin" not in response.headers
