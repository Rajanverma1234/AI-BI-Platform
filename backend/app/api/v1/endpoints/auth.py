"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import AuthRateLimit
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.common import ErrorResponse
from app.schemas.user import UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    dependencies=[AuthRateLimit],
    responses={409: {"model": ErrorResponse, "description": "Email already registered"}},
)
async def register(payload: RegisterRequest, session: DbSession) -> UserResponse:
    """Register a new user. The password is stored as an Argon2id hash."""
    user = await auth_service.register_user(session, payload)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for an access token",
    dependencies=[AuthRateLimit],
    responses={401: {"model": ErrorResponse, "description": "Invalid credentials"}},
)
async def login(payload: LoginRequest, session: DbSession) -> TokenResponse:
    """Authenticate and issue a JWT access token."""
    user = await auth_service.authenticate(session, payload)
    return auth_service.issue_access_token(user)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The authenticated user",
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid token"}},
)
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)
