"""Health endpoint schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "degraded", "error"]


class HealthResponse(BaseModel):
    """Liveness payload - intentionally free of external dependencies."""

    status: Status
    service: str
    version: str
    environment: str


class DependencyStatus(BaseModel):
    name: str
    status: Status
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness payload - reports on each external dependency."""

    status: Status
    service: str
    version: str
    environment: str
    dependencies: list[DependencyStatus]
