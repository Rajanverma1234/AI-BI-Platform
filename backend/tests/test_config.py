"""Configuration parsing tests."""

from __future__ import annotations

import pytest

from app.core.config import (
    DEV_JWT_SECRET_KEY,
    ConfigurationError,
    Settings,
    get_settings,
)

# conftest exports these so the suite runs without PostgreSQL; clear them here
# so the tests observe the real defaults rather than the test harness values.
_HARNESS_VARS = ("ENVIRONMENT", "DATABASE_URL", "CORS_ORIGINS", "LOG_LEVEL", "JWT_SECRET_KEY")


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


#: The minimum a production deployment must supply. Each test below removes or
#: corrupts exactly one of these to show which rule catches it.
NEWLINE = chr(10)

VALID_PRODUCTION = {
    "ENVIRONMENT": "production",
    "JWT_SECRET_KEY": "x" * 64,
    "POSTGRES_PASSWORD": "a-real-generated-password",
    "CORS_ORIGINS": "https://app.example.com",
    "DEBUG": False,
}


def production(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**VALID_PRODUCTION, **overrides})  # type: ignore[arg-type]


def problems(**overrides: object) -> str:
    """The rendered startup error for a given production configuration."""
    return NEWLINE.join(production(**overrides).production_problems())


def test_a_fully_configured_production_environment_starts() -> None:
    settings = production()

    assert settings.is_production is True
    assert settings.CORS_ORIGINS == ["https://app.example.com"]
    assert settings.production_problems() == []


def test_production_requires_an_explicit_jwt_secret() -> None:
    assert "JWT_SECRET_KEY" in problems(JWT_SECRET_KEY=None)


def test_production_rejects_a_short_jwt_secret() -> None:
    assert "at least 32 characters" in problems(JWT_SECRET_KEY="too-short")


def test_production_rejects_debug_mode() -> None:
    assert "DEBUG must be false" in problems(DEBUG=True)


def test_production_rejects_a_wildcard_cors_origin() -> None:
    """A wildcard plus credentialed requests is the classic CORS mistake."""
    assert "must not contain" in problems(CORS_ORIGINS="*")


def test_production_rejects_plaintext_http_origins() -> None:
    assert "https://" in problems(CORS_ORIGINS="http://app.example.com")


def test_production_rejects_a_default_database_password() -> None:
    assert "POSTGRES_PASSWORD" in problems(POSTGRES_PASSWORD="postgres")


def test_the_startup_error_never_contains_a_secret_value() -> None:
    """Regression: the tail of JWT_SECRET_KEY used to reach the logs.

    The checks were a pydantic ``model_validator``, and pydantic wraps a
    validator's exception in a ``ValidationError`` carrying a truncated repr of
    the input - which included part of the signing key. They now run outside
    the model so the message names variables and never carries a value.
    """
    secret = "SUPERSECRETVALUE-abcdefghijklmnopqrstuvwxyz0123456789"
    password = "PRIVATEDBPASSWORD-0123456789"

    message = problems(DEBUG=True, JWT_SECRET_KEY=secret, POSTGRES_PASSWORD=password)

    assert message, "this configuration should be rejected"
    assert secret not in message
    assert password not in message
    # Not even a fragment of either.
    assert "wxyz0123" not in message
    assert "PRIVATEDB" not in message


def test_get_settings_refuses_to_return_an_unsafe_production_configuration(
    monkeypatch,
) -> None:
    """Fail-fast is what stops an insecure deployment from serving traffic."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError, match="Invalid production configuration"):
        get_settings()

    get_settings.cache_clear()


def test_a_supplied_database_url_bypasses_the_password_check() -> None:
    """The operator owns the credentials inside a full DATABASE_URL."""
    settings = production(
        POSTGRES_PASSWORD="postgres",
        DATABASE_URL="postgresql+asyncpg://user:generated@db.internal:5432/aibi",
    )

    assert settings.database_url.endswith("/aibi")


def test_every_production_problem_is_reported_at_once() -> None:
    """One restart should surface the whole list, not the first failure."""
    message = NEWLINE.join(
        Settings(_env_file=None, ENVIRONMENT="production", DEBUG=True).production_problems()
    )

    assert "JWT_SECRET_KEY" in message
    assert "DEBUG must be false" in message
    assert "POSTGRES_PASSWORD" in message


def test_development_keeps_working_without_production_configuration() -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="development")

    assert settings.is_production is False
    assert settings.CORS_ORIGINS == ["http://localhost:5173"]
    assert settings.production_problems() == []


def test_non_production_falls_back_to_a_marked_dev_secret() -> None:
    settings = Settings(_env_file=None, ENVIRONMENT="development")

    assert settings.JWT_SECRET_KEY is None
    assert settings.jwt_secret_key == DEV_JWT_SECRET_KEY
    assert "development-only" in settings.jwt_secret_key


def test_explicit_jwt_secret_is_used_when_provided() -> None:
    settings = Settings(_env_file=None, JWT_SECRET_KEY="from-the-environment")

    assert settings.jwt_secret_key == "from-the-environment"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_no_credentials_are_hard_coded() -> None:
    settings = Settings(_env_file=None)

    assert settings.ANTHROPIC_API_KEY is None
    assert settings.OPENAI_API_KEY is None
