"""Rate limiting for our own API (brief §32) - a simple in-process sliding
window keyed by client IP. Deliberately not a distributed rate limiter
(no Redis dependency for this): Phase 1 runs a single backend instance,
and this is meant to stop accidental hammering (a buggy frontend loop, a
misbehaving script), not to be a hardened anti-abuse system for a
multi-instance deployment. If this backend is ever scaled horizontally,
this should move to a Redis-backed limiter instead.
"""

import time
from collections import defaultdict, deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import get_settings

settings = get_settings()

# Never rate-limit the WebSocket upgrade - a dashboard tab holds exactly one
# long-lived connection, so counting it against the same budget as REST
# polling would make the live feed the first thing to break under load.
_EXEMPT_PATH_PREFIXES = ("/ws",)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, requests_per_minute: int) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.requests_per_minute <= 0 or request.url.path.startswith(_EXEMPT_PATH_PREFIXES):
            return await call_next(request)

        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits[client_key]

        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()

        if len(hits) >= self.requests_per_minute:
            retry_after = max(1, int(self.window_seconds - (now - hits[0])))
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        return await call_next(request)
