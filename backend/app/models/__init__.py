"""ORM models.

Importing every model here guarantees they are registered on ``Base.metadata``
before Alembic autogenerate or ``create_all`` inspects it.
"""

from app.db.base import Base
from app.models.dashboard import Dashboard, DashboardWidget, WidgetType
from app.models.dataset import Dataset, DatasetFileType, DatasetStatus
from app.models.dataset_version import DatasetVersion
from app.models.insight_run import InsightRun
from app.models.nlq_query import NlqQuery
from app.models.project import Project
from app.models.report import (
    Report,
    ReportFileFormat,
    ReportStatus,
    ReportTemplateName,
)
from app.models.user import User
from app.models.workspace import Workspace

__all__ = [
    "Base",
    "Dashboard",
    "DashboardWidget",
    "Dataset",
    "DatasetFileType",
    "DatasetStatus",
    "DatasetVersion",
    "InsightRun",
    "NlqQuery",
    "Project",
    "Report",
    "ReportFileFormat",
    "ReportStatus",
    "ReportTemplateName",
    "User",
    "WidgetType",
    "Workspace",
]
