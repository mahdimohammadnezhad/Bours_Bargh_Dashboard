import json
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class CacheClient:
    """Thin Redis wrapper that never raises: a cache outage degrades to
    cache-miss behavior (callers fall back to the database) instead of
    crashing the request path.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: redis.Redis | None = None
        self._available = True

    async def connect(self) -> None:
        try:
            self._client = redis.from_url(self._url, decode_responses=True, socket_connect_timeout=3)
            await self._client.ping()
            self._available = True
            logger.info("Redis connected at %s", self._url)
        except Exception as exc:  # pragma: no cover - environment dependent
            self._available = False
            logger.warning("Redis unavailable (%s) - cache will no-op, DB is source of truth", exc)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def get_json(self, key: str) -> Any | None:
        if not self._available or self._client is None:
            return None
        try:
            raw = await self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis GET failed for %s: %s", key, exc)
            return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if not self._available or self._client is None:
            return
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl_seconds)
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis SET failed for %s: %s", key, exc)

    async def keys(self, pattern: str) -> list[str]:
        if not self._available or self._client is None:
            return []
        try:
            return [k async for k in self._client.scan_iter(match=pattern)]
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis SCAN failed for %s: %s", pattern, exc)
            return []


cache = CacheClient(settings.REDIS_URL)
