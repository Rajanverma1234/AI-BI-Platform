"""Authentication business logic.

No FastAPI imports here - the router adapts these functions to HTTP.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse

logger = get_logger(__name__)

#: Deliberately identical for "no such account" and "wrong password" so the
#: response cannot be used to discover which emails are registered.
_INVALID_CREDENTIALS = "Incorrect email or password."


def normalise_email(email: str) -> str:
    """Emails are matched case-insensitively; store and compare lowercase."""
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User).where(func.lower(User.email) == normalise_email(email))
    )
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def register_user(session: AsyncSession, payload: RegisterRequest) -> User:
    """Create a new account.

    Raises :class:`ConflictError` when the email is already registered.
    """
    email = normalise_email(payload.email)
    if await get_user_by_email(session, email) is not None:
        raise ConflictError("An account with this email already exists.")

    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    await session.flush()
    logger.info("Registered user", extra={"user_id": str(user.id)})
    return user


async def authenticate(session: AsyncSession, payload: LoginRequest) -> User:
    """Verify credentials and return the user.

    Raises :class:`UnauthorizedError` with one generic message for every
    failure mode (unknown email, wrong password, disabled account).
    """
    user = await get_user_by_email(session, payload.email)

    # Runs the hasher even when the user is missing, to keep timing flat.
    password_ok = verify_password(payload.password, user.password_hash if user else None)

    if user is None or not password_ok or not user.is_active:
        raise UnauthorizedError(_INVALID_CREDENTIALS)

    # Transparently upgrade hashes when the cost parameters change.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        session.add(user)

    return user


def issue_access_token(user: User) -> TokenResponse:
    """Mint an access token identifying ``user``."""
    token, expires_in = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in)
