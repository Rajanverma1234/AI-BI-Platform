"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.registry import get_provider
from app.core.config import Settings, get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services import auth_service
from app.storage.base import StorageProvider
from app.storage.registry import get_storage_provider

DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Provider = Annotated[AIProvider, Depends(get_provider)]
#: Configured file storage backend (local filesystem in development).
Storage = Annotated[StorageProvider, Depends(get_storage_provider)]

# auto_error=False so a missing header raises our UnauthorizedError and is
# rendered through the standard error envelope rather than Starlette's default.
_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

BearerToken = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


async def get_current_user(session: DbSession, credentials: BearerToken) -> User:
    """Resolve the authenticated user from the Authorization header.

    Raises :class:`UnauthorizedError` when the token is missing, malformed,
    expired, or no longer maps to an active account.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication credentials were not provided.")

    user_id = decode_access_token(credentials.credentials)
    user = await auth_service.get_user_by_id(session, user_id)

    if user is None or not user.is_active:
        # The token was validly signed but the account is gone or disabled.
        raise UnauthorizedError("Access token is invalid.")

    return user


#: Attach to any route that requires authentication.
CurrentUser = Annotated[User, Depends(get_current_user)]

__all__ = [
    "AppSettings",
    "CurrentUser",
    "DbSession",
    "Provider",
    "Storage",
    "get_current_user",
]
