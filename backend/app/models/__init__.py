"""ORM models.

Importing every model here guarantees they are registered on ``Base.metadata``
before Alembic autogenerate or ``create_all`` inspects it.
"""

from app.db.base import Base
from app.models.project import Project
from app.models.user import User
from app.models.workspace import Workspace

__all__ = ["Base", "Project", "User", "Workspace"]
