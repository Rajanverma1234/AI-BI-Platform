"""Shared pytest fixtures.

The suite runs against an in-memory SQLite database so it needs no external
services. Anything that must be exercised against PostgreSQL belongs in a
separate integration test marked accordingly.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

# Must be set before app modules import settings.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# Argon2 at production cost would add ~100ms to every password operation.
# The algorithm under test is unchanged; only the work factor is reduced.
os.environ.setdefault("PASSWORD_HASH_TIME_COST", "1")
os.environ.setdefault("PASSWORD_HASH_MEMORY_COST", "8192")
os.environ.setdefault("PASSWORD_HASH_PARALLELISM", "1")
# The suite fires far more requests per minute than a human ever would; the
# limiter itself is covered by its own tests.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Project, User, Workspace  # noqa: E402,F401  (register metadata)

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_engine() -> AsyncGenerator:
    """Fresh in-memory schema per test.

    ``StaticPool`` keeps every connection pointed at the same in-memory
    database for the lifetime of the engine.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def app(db_session: AsyncSession):
    """Application instance with the DB dependency pointed at the test session."""
    application = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


# --- Authentication helpers --------------------------------------------------

API = "/api/v1"
DEFAULT_PASSWORD = "correct-horse-battery"


async def register_and_login(
    client: AsyncClient,
    email: str,
    password: str = DEFAULT_PASSWORD,
    display_name: str | None = None,
) -> str:
    """Register an account and return its bearer token."""
    body: dict[str, str] = {"email": email, "password": password}
    if display_name is not None:
        body["display_name"] = display_name

    registered = await client.post(f"{API}/auth/register", json=body)
    assert registered.status_code == 201, registered.text

    logged_in = await client.post(
        f"{API}/auth/login", json={"email": email, "password": password}
    )
    assert logged_in.status_code == 200, logged_in.text
    token: str = logged_in.json()["access_token"]
    return token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def user_token(client: AsyncClient) -> str:
    """Token for the primary test user."""
    return await register_and_login(client, "owner@example.com", display_name="Owner")


@pytest.fixture
async def other_user_token(client: AsyncClient) -> str:
    """Token for a second, unrelated user - used for tenancy checks."""
    return await register_and_login(client, "intruder@example.com")


@pytest.fixture
async def workspace(client: AsyncClient, user_token: str) -> dict:
    """A workspace owned by the primary test user."""
    response = await client.post(
        f"{API}/workspaces",
        json={"name": "Analytics", "slug": "analytics"},
        headers=auth_headers(user_token),
    )
    assert response.status_code == 201, response.text
    return response.json()
