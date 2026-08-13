"""Aggregated v1 API router.

Future feature routers are mounted here; ``app.main`` only ever sees this one.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    dataset_analysis,
    datasets,
    health,
    project_lookup,
    projects,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(projects.router)
api_router.include_router(project_lookup.router)
api_router.include_router(datasets.router)
api_router.include_router(dataset_analysis.router)
