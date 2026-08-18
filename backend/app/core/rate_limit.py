"""In-process rate limiting.

A fixed-window counter keyed by client identity, applied as a FastAPI
dependency so each route declares its own budget:

    @router.post("/login", dependencies=[AuthRateLimit])

**Scope, stated plainly.** The counters live in this process. With one API
container that is the whole story; behind N replicas each replica enforces the
limit independently, so the effective ceiling is N x the configured value.
That is a deliberate trade: it costs no infrastructure, it is correct for the
single-container deployment this project ships, and it still stops the runaway
loop and the credential-stuffing script that these limits exist for. A
multi-replica deployment that needs an exact global limit should enforce it at
the ingress/gateway, or swap :class:`FixedWindowLimiter` for a Redis-backed
implementation - the dependency surface would not change. See
``docs/security.md``.

Identity is the authenticated user when there is one and the client IP
otherwise, so one noisy tenant cannot exhaust another's budget, and an
unauthenticated flood is still bounded per source.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Window length. One minute matches how the limits are expressed.
WINDOW_SECONDS = 60
#: Distinct keys tracked before the oldest are evicted. Bounds memory under a
#: spray of unique IPs; eviction only ever forgives, never over-restricts.
MAX_TRACKED_KEYS = 20_000


class RateLimitExceeded(AppError):
    """429 with a Retry-After hint. Rendered through the standard envelope."""

    status_code = 429
    code = "rate_limited"


class FixedWindowLimiter:
    """Per-key request counter over a fixed window.

    Thread-safe: FastAPI runs sync dependencies in a worker thread pool, so the
    counters can be touched from several threads at once.
    """

    def __init__(self) -> None:
        self._counters: OrderedDict[tuple[str, int], int] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        """Record a request. Returns (allowed, seconds until the window resets)."""
        moment = time.time() if now is None else now
        window = int(moment // WINDOW_SECONDS)
        reset_in = int(WINDOW_SECONDS - (moment % WINDOW_SECONDS)) or WINDOW_SECONDS
        bucket = (key, window)

        with self._lock:
            # Drop counters from windows that have already closed.
            for tracked in list(self._counters):
                if tracked[1] < window:
                    del self._counters[tracked]

            count = self._counters.get(bucket, 0) + 1
            self._counters[bucket] = count
            self._counters.move_to_end(bucket)

            while len(self._counters) > MAX_TRACKED_KEYS:
                self._counters.popitem(last=False)

        return count <= limit, reset_in

    def reset(self) -> None:
        """Clear every counter. Used by tests."""
        with self._lock:
            self._counters.clear()


#: Process-wide limiter. Shared by every rate-limited route.
limiter = FixedWindowLimiter()


def client_key(request: Request, scope: str) -> str:
    """Identify the caller: authenticated user first, then client address.

    The bearer token is hashed rather than stored, so a key never carries a
    credential even into memory-dumped state. The token is only a fallback -
    ``request.state.user_id`` is set once a route has resolved the user.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"{scope}:user:{user_id}"

    authorization = request.headers.get("authorization")
    if authorization:
        # Cheap, non-reversible discriminator. Never the token itself.
        return f"{scope}:token:{hash(authorization) & 0xFFFFFFFF:08x}"

    forwarded = request.headers.get("x-forwarded-for")
    address = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return f"{scope}:ip:{address}"


class RateLimit:
    """Dependency factory: ``Depends(RateLimit("auth", lambda: settings.X))``."""

    def __init__(self, scope: str, limit_getter: object) -> None:
        self.scope = scope
        self._limit_getter = limit_getter

    def __call__(self, request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        limit = int(self._limit_getter())  # type: ignore[operator]
        if limit <= 0:
            return

        key = client_key(request, self.scope)
        allowed, reset_in = limiter.hit(key, limit)
        if allowed:
            return

        # The path is logged, never the key - it can encode a token hash.
        logger.warning(
            "Rate limit exceeded on %s (scope=%s, limit=%d/min)",
            request.url.path,
            self.scope,
            limit,
        )
        raise RateLimitExceeded(
            "Too many requests. Please wait a moment and try again.",
            details={"retry_after_seconds": reset_in, "limit_per_minute": limit},
        )


#: Credential-guessing surfaces: login, registration, password operations.
AuthRateLimit = Depends(RateLimit("auth", lambda: settings.RATE_LIMIT_AUTH_PER_MINUTE))
#: Endpoints that call an AI provider, and therefore cost money per request.
AiRateLimit = Depends(RateLimit("ai", lambda: settings.RATE_LIMIT_AI_PER_MINUTE))
#: Expensive local work: uploads, report rendering, insight runs, refreshes.
HeavyRateLimit = Depends(RateLimit("heavy", lambda: settings.RATE_LIMIT_HEAVY_PER_MINUTE))
#: Ordinary authenticated traffic.
DefaultRateLimit = Depends(RateLimit("default", lambda: settings.RATE_LIMIT_DEFAULT_PER_MINUTE))

#: Annotated aliases for routes that prefer a parameter to a dependency list.
AuthThrottle = Annotated[None, AuthRateLimit]
AiThrottle = Annotated[None, AiRateLimit]
HeavyThrottle = Annotated[None, HeavyRateLimit]
