"""Health endpoint contract tests."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings

HEALTH_URL = f"{settings.API_V1_PREFIX}/health"


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get(HEALTH_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == settings.PROJECT_NAME
    assert body["version"] == settings.VERSION
    assert body["environment"] == "test"


async def test_health_is_versioned_under_api_v1(client: AsyncClient) -> None:
    assert HEALTH_URL == "/api/v1/health"
    assert (await client.get("/health")).status_code == 404


async def test_health_sets_request_id_header(client: AsyncClient) -> None:
    response = await client.get(HEALTH_URL)

    assert response.headers.get("X-Request-ID")


async def test_health_echoes_supplied_request_id(client: AsyncClient) -> None:
    response = await client.get(HEALTH_URL, headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


async def test_readiness_reports_dependencies(client: AsyncClient) -> None:
    response = await client.get(f"{HEALTH_URL}/ready")

    assert response.status_code == 200
    body = response.json()
    names = {dep["name"] for dep in body["dependencies"]}
    assert names == {"database", "ai_provider"}
    assert body["status"] == "ok"


async def test_root_returns_service_metadata(client: AsyncClient) -> None:
    body = (await client.get("/")).json()

    assert body["service"] == settings.PROJECT_NAME
    assert body["health"] == HEALTH_URL


async def test_openapi_schema_exposes_health(client: AsyncClient) -> None:
    schema = (await client.get(f"{settings.API_V1_PREFIX}/openapi.json")).json()

    assert HEALTH_URL in schema["paths"]
