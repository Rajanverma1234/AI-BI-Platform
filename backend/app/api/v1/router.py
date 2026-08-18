"""Aggregated v1 API router.

Future feature routers are mounted here; ``app.main`` only ever sees this one.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    advanced_analytics,
    ai_analyst,
    auth,
    dashboards,
    dataset_analysis,
    dataset_analytics,
    dataset_visualization,
    datasets,
    health,
    insights,
    nlq,
    project_lookup,
    projects,
    reports,
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
api_router.include_router(dataset_visualization.router)
api_router.include_router(dataset_analytics.router)
api_router.include_router(ai_analyst.router)
api_router.include_router(nlq.router)
api_router.include_router(advanced_analytics.router)
api_router.include_router(reports.router)
api_router.include_router(insights.router)
api_router.include_router(insights.run_router)
api_router.include_router(dashboards.router)
api_router.include_router(dashboards.dashboard_router)
