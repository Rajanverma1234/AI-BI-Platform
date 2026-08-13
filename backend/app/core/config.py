"""Environment-based application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    """Application settings loaded from the environment (and an optional .env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    PROJECT_NAME: str = "AI BI Platform"
    VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Logging -------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # --- Database ------------------------------------------------------------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "aibi"
    POSTGRES_PASSWORD: str = "aibi"
    POSTGRES_DB: str = "aibi"
    # Full override; when set it wins over the discrete POSTGRES_* values.
    DATABASE_URL: str | None = None
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # --- CORS ----------------------------------------------------------------
    # NoDecode disables pydantic-settings' source-level JSON decoding so the
    # validator below can accept a comma-separated string as well as JSON.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- AI providers --------------------------------------------------------
    # Never commit real keys; these are read from the environment only.
    AI_PROVIDER: str = "null"
    AI_MODEL: str | None = None
    AI_REQUEST_TIMEOUT: float = 60.0
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept a JSON list or a comma-separated string, from env or kwargs."""
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if raw.startswith("["):
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"CORS_ORIGINS is not valid JSON: {raw!r}") from exc
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL for the application engine."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so the environment is parsed exactly once."""
    return Settings()


settings = get_settings()
