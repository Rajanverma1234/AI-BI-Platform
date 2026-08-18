"""Environment-based application configuration."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]

#: Used only when JWT_SECRET_KEY is unset outside production. Named so that it
#: is unmistakable in a token dump or a config listing.
DEV_JWT_SECRET_KEY = "insecure-development-only-jwt-secret-do-not-use-in-production"

#: Database passwords that are fine locally and must never reach production.
INSECURE_DB_PASSWORDS = frozenset({"aibi", "postgres", "password", "change-me-locally", ""})


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
    #: Pattern for origins that cannot be listed up front. Preview deployments
    #: are the reason this exists: Vercel gives every push a fresh hostname
    #: (https://<project>-<hash>-<team>.vercel.app), so no fixed list can cover
    #: them and the preflight fails with a 400 that carries no
    #: Access-Control-Allow-Origin. Starlette full-matches the pattern against
    #: the Origin header, so it is anchored implicitly. Keep it narrow - it is
    #: checked in addition to CORS_ORIGINS, never instead of it.
    CORS_ORIGIN_REGEX: str | None = None
    #: Public URL of the frontend, used in docs and deployment checks.
    FRONTEND_URL: str | None = None

    # --- HTTP hardening ------------------------------------------------------
    #: Emit security response headers. On by default in every environment.
    SECURITY_HEADERS_ENABLED: bool = True
    #: Send Strict-Transport-Security. Only meaningful behind HTTPS, so it is
    #: off unless explicitly enabled - sending it over plain HTTP can lock a
    #: browser out of a host that is not yet TLS-terminated.
    HSTS_ENABLED: bool = False
    HSTS_MAX_AGE_SECONDS: int = 63_072_000
    #: Content-Security-Policy for API responses. The API serves JSON and the
    #: OpenAPI pages only, so it can be strict; the frontend is served
    #: separately and carries its own policy.
    CONTENT_SECURITY_POLICY: str = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    #: Ceiling on any request body, independent of the upload limit. Guards the
    #: JSON endpoints, which would otherwise accept an unbounded payload.
    MAX_REQUEST_BODY_MB: int = 64

    # --- Rate limiting -------------------------------------------------------
    #: Master switch. Disabled in tests so the suite is not throttled.
    RATE_LIMIT_ENABLED: bool = True
    #: Requests per window for ordinary authenticated endpoints.
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 120
    #: Login, registration and anything else that guesses credentials.
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    #: AI-backed endpoints, which cost money per call.
    RATE_LIMIT_AI_PER_MINUTE: int = 20
    #: Expensive but local work: uploads, reports, insight runs, refreshes.
    RATE_LIMIT_HEAVY_PER_MINUTE: int = 30

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

    @field_validator("CORS_ORIGIN_REGEX")
    @classmethod
    def _compile_cors_origin_regex(cls, value: str | None) -> str | None:
        """Reject a pattern that Starlette would later fail to compile.

        A bad pattern here would otherwise surface as a 500 on the first
        cross-origin request rather than at start-up. The pattern is not a
        secret, so echoing it in the error is safe.
        """
        if value is None or not value.strip():
            return None
        pattern = value.strip()
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"CORS_ORIGIN_REGEX is not a valid regex ({exc}): {pattern}") from exc
        return pattern

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

    @property
    def max_request_body_bytes(self) -> int:
        return self.MAX_REQUEST_BODY_MB * 1024 * 1024

    def production_problems(self) -> list[str]:
        """Every reason this configuration is unsafe for production.

        Returns the list rather than raising, and is deliberately *not* a
        pydantic validator: a validator's exception is wrapped in a
        ``ValidationError`` that embeds a truncated repr of the input, which
        put the tail of ``JWT_SECRET_KEY`` into the startup error and therefore
        into the logs. ``get_settings`` raises on the returned list instead, so
        the message names variables and never carries a value.
        """
        if not self.is_production:
            return []

        problems: list[str] = []

        if not self.JWT_SECRET_KEY:
            problems.append(
                "JWT_SECRET_KEY must be set (generate with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(64))\"`)."
            )
        elif len(self.JWT_SECRET_KEY) < 32:
            problems.append("JWT_SECRET_KEY must be at least 32 characters.")

        if self.DEBUG:
            problems.append("DEBUG must be false in production.")

        # A wildcard origin plus credentialed requests is the classic mistake.
        if "*" in self.CORS_ORIGINS:
            problems.append("CORS_ORIGINS must not contain '*' in production.")
        if not self.CORS_ORIGINS:
            problems.append("CORS_ORIGINS must list the frontend origin(s).")
        insecure_origins = [
            origin
            for origin in self.CORS_ORIGINS
            if origin.startswith("http://") and "localhost" not in origin
        ]
        if insecure_origins:
            problems.append(
                "CORS_ORIGINS must use https:// in production: "
                + ", ".join(insecure_origins)
            )

        # A regex is the one place a wildcard can slip past the "*" check above.
        # These probes are origins no deployment of this app will ever serve
        # from, so a match means the pattern would hand credentialed access to
        # any site that asks.
        if self.CORS_ORIGIN_REGEX:
            compiled = re.compile(self.CORS_ORIGIN_REGEX)
            matched = [
                probe
                for probe in ("https://attacker.example", "http://attacker.example")
                if compiled.fullmatch(probe)
            ]
            if matched:
                problems.append(
                    "CORS_ORIGIN_REGEX also matches unrelated origins "
                    f"({', '.join(matched)}); narrow it to your own frontend hosts."
                )

        # Only checked when the discrete values are in use; a DATABASE_URL is
        # supplied whole and its credentials are the operator's business.
        if not self.DATABASE_URL and self.POSTGRES_PASSWORD in INSECURE_DB_PASSWORDS:
            problems.append("POSTGRES_PASSWORD must not be a default value in production.")

        return problems

    @property
    def jwt_secret_key(self) -> str:
        """The signing key. Outside production an obvious placeholder is used."""
        return self.JWT_SECRET_KEY or DEV_JWT_SECRET_KEY


class ConfigurationError(RuntimeError):
    """Raised at startup when production configuration is unsafe."""


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so the environment is parsed exactly once.

    Production configuration is checked here, so an unsafe deployment fails on
    import with a message that lists the variables to fix and contains no
    secret values.
    """
    resolved = Settings()
    problems = resolved.production_problems()
    if problems:
        bullets = "\n  - ".join(problems)
        raise ConfigurationError(f"Invalid production configuration:\n  - {bullets}")
    return resolved


settings = get_settings()
