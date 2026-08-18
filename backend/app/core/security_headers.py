"""Security response headers and a request body ceiling.

Two small middlewares that the API layer cannot express per-route.

The headers are deliberately conservative for an API: it returns JSON to a
separate origin, so it never needs to be framed, never needs to load a
subresource, and never posts a form. Strict-Transport-Security is the one
header that is off by default - asserting HTTPS-only from a host that is not
yet TLS-terminated locks browsers out of it, so it is opt-in via
``HSTS_ENABLED`` once a certificate is in place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.errors import error_response
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Paths whose HTML the browser must render, so they cannot take the strict
#: API policy. Only present outside production, where docs are disabled.
_DOCS_PATHS = frozenset({"/docs", "/redoc"})

#: Enough for the Swagger/ReDoc bundles, which load from a CDN and use inline
#: styles. Development only - these routes do not exist in production.
_DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "worker-src 'self' blob:; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardening headers to every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if not settings.SECURITY_HEADERS_ENABLED:
            return response

        headers = response.headers
        # Stop browsers guessing a content type; the main defence against a
        # stored file being interpreted as script.
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        # The API needs none of these; denying them shrinks what a successful
        # injection could reach.
        headers.setdefault(
            "Permissions-Policy",
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()",
        )
        headers.setdefault(
            "Content-Security-Policy",
            _DOCS_CSP
            if request.url.path in _DOCS_PATHS
            else settings.CONTENT_SECURITY_POLICY,
        )

        if settings.HSTS_ENABLED:
            headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.HSTS_MAX_AGE_SECONDS}; includeSubDomains",
            )

        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject a request whose declared body exceeds the configured ceiling.

    This is a cheap guard on the JSON endpoints, which would otherwise accept
    an unbounded payload. Dataset uploads have their own, larger limit enforced
    while streaming, so this ceiling is set above it rather than replacing it -
    a body without a ``Content-Length`` still streams and is still checked by
    the storage provider.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                return error_response(400, "bad_request", "Malformed Content-Length header.")

            if length > settings.max_request_body_bytes:
                logger.warning(
                    "Rejected oversized request body on %s (%d bytes)",
                    request.url.path,
                    length,
                )
                return error_response(
                    413,
                    "payload_too_large",
                    f"Request body exceeds the {settings.MAX_REQUEST_BODY_MB} MB limit.",
                )

        return await call_next(request)
