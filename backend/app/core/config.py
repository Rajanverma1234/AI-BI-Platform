"""Environment-based application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]

#: Used only when JWT_SECRET_KEY is unset outside production. Named so that it
#: is unmistakable in a token dump or a config listing.
DEV_JWT_SECRET_KEY = "insecure-development-only-jwt-secret-do-not-use-in-production"


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

    # --- Authentication ------------------------------------------------------
    # No default: a real secret must come from the environment. Production
    # refuses to start without one (see the validator below); other
    # environments fall back to a clearly-marked development value.
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    # Argon2id parameters. Defaults follow the argon2-cffi recommendations.
    PASSWORD_HASH_TIME_COST: int = 3
    PASSWORD_HASH_MEMORY_COST: int = 65536
    PASSWORD_HASH_PARALLELISM: int = 4

    # --- Dataset uploads and storage -----------------------------------------
    # Selected at runtime; "local" is the development filesystem provider.
    STORAGE_PROVIDER: str = "local"
    #: Root directory for the local provider. Relative paths resolve from the
    #: backend working directory.
    STORAGE_LOCAL_ROOT: str = "./var/storage"
    #: Upload ceiling. Enforced while streaming, never by loading the file.
    MAX_UPLOAD_SIZE_MB: int = 50
    #: Extensions accepted by the dataset upload endpoint.
    ALLOWED_DATASET_EXTENSIONS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["csv", "xlsx"]
    )
    #: Rows scanned to infer column types; keeps large files off the heap.
    DATASET_TYPE_SAMPLE_ROWS: int = 1000
    #: Rows per chunk when counting CSV rows.
    DATASET_CSV_CHUNK_ROWS: int = 50_000

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

    @field_validator("ALLOWED_DATASET_EXTENSIONS", mode="before")
    @classmethod
    def _split_extensions(cls, value: object) -> object:
        """Accept JSON or CSV, and normalise to bare lowercase extensions."""
        if isinstance(value, str):
            raw = value.strip()
            items = json.loads(raw) if raw.startswith("[") else raw.split(",")
        elif isinstance(value, list):
            items = value
        else:
            return value
        return [str(item).strip().lower().lstrip(".") for item in items if str(item).strip()]

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def max_upload_size_bytes(self) -> int:
        """Upload ceiling in bytes, derived from the configured megabytes."""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

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

    @model_validator(mode="after")
    def _require_jwt_secret_in_production(self) -> Settings:
        """Fail fast rather than sign production tokens with a known key."""
        if self.is_production and not self.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY must be set when ENVIRONMENT=production.")
        return self

    @property
    def jwt_secret_key(self) -> str:
        """The signing key. Outside production an obvious placeholder is used."""
        return self.JWT_SECRET_KEY or DEV_JWT_SECRET_KEY


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so the environment is parsed exactly once."""
    return Settings()


settings = get_settings()
