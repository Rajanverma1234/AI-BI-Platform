"""User schemas.

``password_hash`` is deliberately absent from every response model here, so it
cannot leak even if a route returns a whole ORM object.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class UserResponse(ORMModel):
    """Public representation of a user."""

    id: uuid.UUID
    email: str
    display_name: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(ORMModel):
    """Self-service profile fields a user may change."""

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
