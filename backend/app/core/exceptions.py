"""Application-level exception types.

Every expected failure raised by services should be an :class:`AppError`
subclass so the centralised handlers can render a consistent error envelope.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all handled application errors."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "The request payload is invalid."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "The resource already exists or conflicts with the current state."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication is required."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have access to this resource."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "A required dependency is unavailable."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"
    message = "This file type is not supported."


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"
    message = "The uploaded file is too large."


class StorageError(AppError):
    """Raised when the storage backend fails.

    The message is deliberately generic: filesystem paths and bucket names
    must never reach the client.
    """

    status_code = 503
    code = "storage_error"
    message = "The file store is unavailable."


class ProcessingError(AppError):
    """Raised when an uploaded file cannot be parsed."""

    status_code = 422
    code = "processing_error"
    message = "The uploaded file could not be processed."


class ProviderError(AppError):
    """Raised when an external AI provider fails or is misconfigured."""

    status_code = 502
    code = "provider_error"
    message = "The AI provider request failed."
