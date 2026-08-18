"""Security headers, request-size limits and rate limiting.

These guard behaviour that is invisible until it is missing: a header that is
no longer sent, a body ceiling that stops applying, a login endpoint that
happily accepts a thousand attempts a minute.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.rate_limit import FixedWindowLimiter, RateLimitExceeded, client_key, limiter
from app.main import create_app
from tests.conftest import API, DEFAULT_PASSWORD


@pytest.fixture(autouse=True)
def _clear_limiter():
    """Counters are process-wide, so each test starts from a clean slate."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def throttled(monkeypatch):
    """Enable rate limiting, which the suite disables by default."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    return settings


# --- Security headers --------------------------------------------------------


async def test_every_response_carries_the_hardening_headers(client: AsyncClient) -> None:
    response = await client.get(f"{API}/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


async def test_error_responses_are_hardened_too(client: AsyncClient) -> None:
    """A 401 is still a response an attacker sees; it gets the same headers."""
    response = await client.get(f"{API}/workspaces")

    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_hsts_is_off_until_explicitly_enabled(client: AsyncClient) -> None:
    """Asserting HTTPS-only from a plain-HTTP host would lock browsers out."""
    response = await client.get(f"{API}/health")

    assert "Strict-Transport-Security" not in response.headers


async def test_hsts_is_sent_once_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HSTS_ENABLED", True)
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        response = await http_client.get(f"{API}/health")

    assert "max-age=" in response.headers["Strict-Transport-Security"]
    assert "includeSubDomains" in response.headers["Strict-Transport-Security"]


# --- Request size ------------------------------------------------------------


async def test_an_oversized_body_is_rejected_before_it_is_read(
    client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_MB", 1)

    response = await client.post(
        f"{API}/auth/login",
        content=b"x" * (2 * 1024 * 1024),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "payload_too_large"
    # The standard envelope is preserved, request id included.
    assert "request_id" in body


async def test_a_normal_body_is_unaffected(client: AsyncClient) -> None:
    response = await client.post(
        f"{API}/auth/login", json={"email": "nobody@example.com", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 401


# --- Rate limiting -----------------------------------------------------------


def test_the_window_allows_exactly_the_configured_number() -> None:
    local = FixedWindowLimiter()

    results = [local.hit("key", limit=3, now=1000.0)[0] for _ in range(4)]

    assert results == [True, True, True, False]


def test_a_new_window_forgives_the_previous_one() -> None:
    local = FixedWindowLimiter()
    for _ in range(3):
        local.hit("key", limit=3, now=1000.0)

    allowed, _ = local.hit("key", limit=3, now=1061.0)

    assert allowed is True


def test_budgets_are_per_key() -> None:
    local = FixedWindowLimiter()
    for _ in range(3):
        local.hit("noisy", limit=3, now=1000.0)

    allowed, _ = local.hit("quiet", limit=3, now=1000.0)

    assert allowed is True


def fake_request(*, user_id: str | None = None, headers: dict[str, str] | None = None):
    """The three attributes ``client_key`` reads, without a real ASGI scope."""
    return SimpleNamespace(
        state=SimpleNamespace(user_id=user_id),
        headers=headers or {},
        client=None,
    )


def test_an_authenticated_caller_is_keyed_by_identity() -> None:
    """One tenant behind a shared address must not exhaust another's budget."""
    assert client_key(fake_request(user_id="user-1"), "ai") == "ai:user:user-1"


def test_a_token_is_never_placed_in_the_rate_limit_key() -> None:
    secret = "Bearer super-secret-token-value"

    key = client_key(fake_request(headers={"authorization": secret}), "auth")

    assert "super-secret-token-value" not in key
    assert key.startswith("auth:token:")


async def test_login_is_throttled(client: AsyncClient, throttled) -> None:
    """Credential guessing is the reason this limit exists."""
    limit = settings.RATE_LIMIT_AUTH_PER_MINUTE
    credentials = {"email": "nobody@example.com", "password": DEFAULT_PASSWORD}

    statuses = [
        (await client.post(f"{API}/auth/login", json=credentials)).status_code
        for _ in range(limit + 2)
    ]

    assert statuses[0] == 401
    assert statuses[-1] == 429


async def test_a_throttled_response_uses_the_standard_envelope(
    client: AsyncClient, throttled, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 1)
    credentials = {"email": "nobody@example.com", "password": DEFAULT_PASSWORD}

    await client.post(f"{API}/auth/login", json=credentials)
    response = await client.post(f"{API}/auth/login", json=credentials)

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["details"]["limit_per_minute"] == 1
    assert body["error"]["details"]["retry_after_seconds"] > 0
    # No hint about which account was tried.
    assert "nobody@example.com" not in response.text


async def test_ordinary_reads_are_not_throttled_by_the_auth_budget(
    client: AsyncClient, throttled, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 1)
    credentials = {"email": "nobody@example.com", "password": DEFAULT_PASSWORD}
    await client.post(f"{API}/auth/login", json=credentials)
    await client.post(f"{API}/auth/login", json=credentials)

    # A different scope, so the exhausted auth budget does not apply.
    health = await client.get(f"{API}/health")

    assert health.status_code == 200


def test_rate_limit_error_is_a_429_with_a_safe_message() -> None:
    error = RateLimitExceeded("Too many requests.")

    assert error.status_code == 429
    assert error.code == "rate_limited"
