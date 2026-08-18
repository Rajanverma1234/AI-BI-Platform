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
    dependencies = {dep["name"]: dep for dep in body["dependencies"]}
    assert set(dependencies) == {"database", "ai_provider"}
    assert dependencies["database"]["status"] == "ok"


async def test_readiness_is_degraded_but_serving_without_an_ai_provider(
    client: AsyncClient,
) -> None:
    """AI is optional, so its absence degrades readiness without failing it.

    The suite runs on the null provider, which reports itself as unconfigured.
    That must surface honestly as `degraded` - but still HTTP 200, because an
    orchestrator gates traffic on the status code and the platform serves
    every non-AI feature perfectly well without a provider.
    """
    response = await client.get(f"{HEALTH_URL}/ready")

    assert response.status_code == 200
    body = response.json()
    ai = next(dep for dep in body["dependencies"] if dep["name"] == "ai_provider")
    assert ai["status"] == "degraded"
    assert "not configured" in (ai["detail"] or "")
    assert body["status"] == "degraded"


async def test_readiness_never_leaks_connection_details(client: AsyncClient) -> None:
    body = (await client.get(f"{HEALTH_URL}/ready")).text

    for secret in ["password", "postgresql://", "api_key", "sk-"]:
        assert secret not in body.lower()


async def test_root_returns_service_metadata(client: AsyncClient) -> None:
    body = (await client.get("/")).json()

    assert body["service"] == settings.PROJECT_NAME
    assert body["health"] == HEALTH_URL


async def test_openapi_schema_exposes_health(client: AsyncClient) -> None:
    schema = (await client.get(f"{settings.API_V1_PREFIX}/openapi.json")).json()

    assert HEALTH_URL in schema["paths"]
