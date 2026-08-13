"""Aggregated v1 API router.

Future feature routers are mounted here; ``app.main`` only ever sees this one.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router)
