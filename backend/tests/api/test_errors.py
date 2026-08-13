"""Centralised error handling produces a consistent envelope."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import register_exception_handlers
from app.core.exceptions import ConflictError, NotFoundError
from app.core.middleware import RequestContextMiddleware

# Stands in for anything sensitive an internal traceback might carry; it must
# never reach the client.
LEAKY_DETAIL = "connection string postgres://user:s3cret@db/app"


def _error_app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)

    @application.get("/missing")
    async def _missing() -> None:
        raise NotFoundError("Workspace not found.")

    @application.get("/conflict")
    async def _conflict() -> None:
        raise ConflictError(details={"field": "slug"})

    @application.get("/boom")
    async def _boom() -> None:
        raise RuntimeError(LEAKY_DETAIL)

    @application.get("/typed/{item_id}")
    async def _typed(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    return application


async def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=_error_app(), raise_app_exceptions=False),
        base_url="http://test",
    )


async def test_app_error_maps_to_status_and_code() -> None:
    async with await _client() as client:
        response = await client.get("/missing")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Workspace not found.",
        "details": None,
    }


async def test_app_error_carries_details() -> None:
    async with await _client() as client:
        response = await client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"field": "slug"}


async def test_unhandled_exception_is_masked_as_internal_error() -> None:
    async with await _client() as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert LEAKY_DETAIL not in response.text


async def test_request_validation_error_returns_422_envelope() -> None:
    async with await _client() as client:
        response = await client.get("/typed/not-an-int")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]


async def test_unknown_route_returns_envelope() -> None:
    async with await _client() as client:
        response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
