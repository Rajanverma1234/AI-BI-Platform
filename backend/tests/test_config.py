"""Configuration parsing tests."""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings

# conftest exports these so the suite runs without PostgreSQL; clear them here
# so the tests observe the real defaults rather than the test harness values.
_HARNESS_VARS = ("ENVIRONMENT", "DATABASE_URL", "CORS_ORIGINS", "LOG_LEVEL")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _HARNESS_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_sane() -> None:
    settings = Settings(_env_file=None)

    assert settings.API_V1_PREFIX == "/api/v1"
    assert settings.ENVIRONMENT == "development"
    assert settings.is_production is False


def test_database_url_is_built_from_discrete_parts() -> None:
    settings = Settings(
        _env_file=None,
        POSTGRES_USER="u",
        POSTGRES_PASSWORD="p",
        POSTGRES_HOST="db",
        POSTGRES_PORT=5433,
        POSTGRES_DB="aibi",
    )

    assert settings.database_url == "postgresql+asyncpg://u:p@db:5433/aibi"


def test_explicit_database_url_wins() -> None:
    settings = Settings(_env_file=None, DATABASE_URL="sqlite+aiosqlite:///./local.db")

    assert settings.database_url == "sqlite+aiosqlite:///./local.db"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        ('["http://a.test"]', ["http://a.test"]),
        ("http://a.test", ["http://a.test"]),
    ],
)
def test_cors_origins_accept_csv_and_json(raw: str, expected: list[str]) -> None:
    settings = Settings(_env_file=None, CORS_ORIGINS=raw)

    assert settings.CORS_ORIGINS == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        ('["http://a.test","http://b.test"]', ["http://a.test", "http://b.test"]),
    ],
)
def test_cors_origins_parse_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    """Env vars are read by a different code path than init kwargs.

    A comma-separated value used to blow up at import time, so this case is
    covered explicitly.
    """
    monkeypatch.setenv("CORS_ORIGINS", raw)
    settings = Settings(_env_file=None)

    assert settings.CORS_ORIGINS == expected


def test_log_level_is_normalised() -> None:
    assert Settings(_env_file=None, LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"


def test_production_hides_docs_flag() -> None:
    assert Settings(_env_file=None, ENVIRONMENT="production").is_production is True


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_no_credentials_are_hard_coded() -> None:
    settings = Settings(_env_file=None)

    assert settings.ANTHROPIC_API_KEY is None
    assert settings.OPENAI_API_KEY is None
