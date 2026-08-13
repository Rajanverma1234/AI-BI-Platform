"""Password hashing and JWT access tokens.

This module is deliberately free of FastAPI and database imports: it is pure
cryptographic plumbing that services and dependencies build on.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

#: Token category, so a future refresh token cannot be replayed as an access token.
ACCESS_TOKEN_TYPE: Final = "access"

#: Stored for accounts that must never authenticate with a password (e.g. rows
#: that predate authentication). It is not a valid Argon2 hash, so verification
#: always fails - while still running a real hash first to keep timing flat.
UNUSABLE_PASSWORD_HASH: Final = "!"

_hasher = PasswordHasher(
    time_cost=settings.PASSWORD_HASH_TIME_COST,
    memory_cost=settings.PASSWORD_HASH_MEMORY_COST,
    parallelism=settings.PASSWORD_HASH_PARALLELISM,
)

#: Hash of a throwaway password, used to burn comparable CPU time when an
#: account does not exist so login cannot be timed to enumerate emails.
_DUMMY_HASH: Final = _hasher.hash("timing-equalisation-placeholder")


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password against a stored hash.

    Always performs one hash comparison, even when the account is missing or
    has no usable password, so failures take a similar amount of time.
    """
    if not password_hash or password_hash == UNUSABLE_PASSWORD_HASH:
        with contextlib.suppress(VerifyMismatchError, VerificationError, InvalidHashError):
            _hasher.verify(_DUMMY_HASH, password)
        return False
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash uses outdated Argon2 parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def create_access_token(
    subject: uuid.UUID | str,
    *,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Sign an access token for ``subject``.

    Returns the encoded token and its lifetime in seconds.
    """
    lifetime = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    issued_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": ACCESS_TOKEN_TYPE,
        "iat": issued_at,
        "exp": issued_at + lifetime,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> uuid.UUID:
    """Validate an access token and return the user id it identifies.

    Raises :class:`UnauthorizedError` for anything malformed, expired,
    wrongly-signed or of the wrong token type.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Access token is invalid.") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise UnauthorizedError("Access token is invalid.")

    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError("Access token is invalid.") from exc
