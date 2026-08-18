"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.security_headers import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.db.session import dispose_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.LOG_LEVEL, settings.LOG_JSON)
    # Values only - never a secret. Enough to confirm what a container booted
    # with without putting a credential in the log stream.
    logger.info(
        "Starting %s v%s (env=%s, storage=%s, ai_provider=%s, rate_limit=%s)",
        settings.PROJECT_NAME,
        settings.VERSION,
        settings.ENVIRONMENT,
        settings.STORAGE_PROVIDER,
        settings.AI_PROVIDER,
        "on" if settings.RATE_LIMIT_ENABLED else "off",
    )
    yield
    # Drain the connection pool so the container exits cleanly rather than
    # letting the orchestrator kill it with sockets open.
    await dispose_engine()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Build the application. Kept as a factory so tests can build isolated apps."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_JSON)

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
        openapi_url=None if settings.is_production else f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    # Middleware runs in reverse registration order, so the request id is
    # established first and is therefore present in every log line and error
    # envelope produced by the layers below it.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Explicit origins only. Never "*": these endpoints are credentialed,
        # and production configuration refuses a wildcard outright.
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
        max_age=600,
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", tags=["meta"], summary="Service metadata")
    async def root() -> dict[str, str]:
        # Deliberately minimal: no dependency, build or configuration detail
        # that would help someone fingerprint the deployment.
        payload = {
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "health": f"{settings.API_V1_PREFIX}/health",
        }
        if not settings.is_production:
            payload["docs"] = "/docs"
        return payload

    return app


app = create_app()
