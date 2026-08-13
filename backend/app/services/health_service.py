"""Health/readiness checks kept out of the route layer."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import get_provider
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.health import DependencyStatus, HealthResponse, ReadinessResponse

logger = get_logger(__name__)


def liveness() -> HealthResponse:
    """Process-level health; must never touch an external dependency."""
    return HealthResponse(
        status="ok",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
    )


async def check_database(session: AsyncSession) -> DependencyStatus:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", exc)
        return DependencyStatus(name="database", status="error", detail=type(exc).__name__)
    return DependencyStatus(name="database", status="ok")


def check_ai_provider() -> DependencyStatus:
    """Configuration-only check - no outbound call is made."""
    try:
        provider = get_provider()
    except Exception as exc:  # pragma: no cover - defensive
        return DependencyStatus(name="ai_provider", status="error", detail=str(exc))
    configured = provider.is_configured()
    return DependencyStatus(
        name="ai_provider",
        status="ok" if configured else "degraded",
        detail=f"{provider.name}{'' if configured else ' (credentials not configured)'}",
    )


async def readiness(session: AsyncSession) -> ReadinessResponse:
    dependencies = [await check_database(session), check_ai_provider()]
    if any(dep.status == "error" for dep in dependencies):
        overall = "error"
    elif any(dep.status == "degraded" for dep in dependencies):
        overall = "degraded"
    else:
        overall = "ok"
    return ReadinessResponse(
        status=overall,
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        dependencies=dependencies,
    )
