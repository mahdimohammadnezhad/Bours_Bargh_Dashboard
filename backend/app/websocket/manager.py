import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger(__name__)


def _json_default(value: Any) -> str:
    # ISO-8601 ("2026-10-11T07:24:03+00:00"), not str()'s space-separated
    # form, which JavaScript's Date only parses on some engines.
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ConnectionManager:
    """Tracks active WebSocket clients and pushes diffs, not full snapshots,
    per connection (except the initial message on connect).
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket connected (total=%d)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WebSocket disconnected (total=%d)", len(self._connections))

    async def send_to(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        try:
            await websocket.send_text(json.dumps(message, default=_json_default))
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebSocket send failed: %s", exc)
            await self.disconnect(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self._connections:
            return
        payload = json.dumps(message, default=_json_default)
        dead: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections)
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)


manager = ConnectionManager()
