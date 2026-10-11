import asyncio
from dataclasses import asdict
from datetime import datetime, timezone

import httpx

from app.cache.redis_client import cache
from app.collectors.base import BaseCollector, NormalizedQuote
from app.collectors.iee_new_collector import IEENewCollector
from app.collectors.iee_old_collector import IEEOldCollector
from app.collectors.tsetmc_collector import TSETMCCollector
from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import SessionLocal, db_write_lock
from app.services.market_service import ensure_data_source, record_cycle
from app.websocket.manager import manager as ws_manager

settings = get_settings()
logger = get_logger(__name__)


def is_active_session(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    # NOTE: Iran market hours are in Iran Standard Time (UTC+3:30); this
    # is a coarse UTC-hour approximation good enough for adaptive polling,
    # not a precise session-boundary source of truth.
    hour = (now.hour + 3) % 24  # rough UTC -> IRST hour shift, minutes ignored
    return settings.MARKET_ACTIVE_HOURS_START <= hour < settings.MARKET_ACTIVE_HOURS_END


class CollectorManager:
    def __init__(self) -> None:
        self.collectors: list[BaseCollector] = [
            TSETMCCollector(),
            IEENewCollector(),
            IEEOldCollector(),
        ]
        self._tasks: list[asyncio.Task] = []
        self._client: httpx.AsyncClient | None = None
        self._stopping = False

    async def start(self) -> None:
        self._client = httpx.AsyncClient(follow_redirects=True)
        async with SessionLocal() as session:
            for collector in self.collectors:
                await ensure_data_source(session, collector)

        self._stopping = False
        for collector in self.collectors:
            task = asyncio.create_task(self._supervise(collector), name=f"collector:{collector.source_id}")
            self._tasks.append(task)
        logger.info("Collector manager started with %d collectors", len(self.collectors))

    async def stop(self) -> None:
        self._stopping = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._client is not None:
            await self._client.aclose()
        logger.info("Collector manager stopped")

    async def _supervise(self, collector: BaseCollector) -> None:
        """Run one collector's poll loop forever; a crash here is caught and
        the loop keeps going with backoff, so one broken collector can never
        take down the others or the process.
        """
        consecutive_task_errors = 0
        while not self._stopping:
            try:
                await self._run_one_cycle(collector)
                consecutive_task_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                consecutive_task_errors += 1
                logger.exception("%s: unexpected error in poll loop: %s", collector.source_id, exc)

            interval = self._effective_interval(collector)
            if consecutive_task_errors:
                interval = min(settings.POLL_INTERVAL_IDLE, interval * (2**consecutive_task_errors))
            await asyncio.sleep(interval)

    async def _run_one_cycle(self, collector: BaseCollector) -> None:
        assert self._client is not None
        result = await collector.run_cycle(self._client)

        async with db_write_lock(), SessionLocal() as session:
            quotes, changed = await record_cycle(session, collector, result)

        if not quotes:
            return

        for quote in quotes:
            await cache.set_json(
                f"quote:{quote.source_id}:{quote.source_symbol}",
                asdict(quote),
                ttl_seconds=settings.CACHE_TTL_SECONDS,
            )

        if changed:
            # Live view = newest quote per symbol. A cycle can also carry
            # older-dated rows for the same symbol (TSETMC's daily history on
            # first sight of a contract); the client keys quotes by symbol, so
            # sending those would overwrite the live value with an old day.
            latest: dict[str, NormalizedQuote] = {}
            for quote in quotes:
                current = latest.get(quote.source_symbol)
                if current is None or quote.observed_at >= current.observed_at:
                    latest[quote.source_symbol] = quote
            await ws_manager.broadcast(
                {
                    "type": "quotes",
                    "source": collector.source_id,
                    "server_time": datetime.now(timezone.utc).isoformat(),
                    # `raw` is included (not stripped) - the frontend needs
                    # it for context that has no dedicated column yet (e.g.
                    # a contract's display name, market-state text). See
                    # docs/DATA_SOURCES.md for what each source puts there.
                    "quotes": [asdict(q) for q in latest.values()],
                }
            )

    def _effective_interval(self, collector: BaseCollector) -> float:
        base = settings.POLL_INTERVAL_ACTIVE if is_active_session() else settings.POLL_INTERVAL_IDLE
        return max(base, collector.state.current_interval, collector.min_poll_interval)

    def health_snapshot(self) -> list[dict]:
        return [
            {
                "source_id": c.source_id,
                "name": c.name,
                "status": c.state.status,
                "last_success_at": c.state.last_success_at,
                "last_error": c.state.last_error,
                "last_error_at": c.state.last_error_at,
                "consecutive_failures": c.state.consecutive_failures,
                "latency_ms": c.state.last_latency_ms,
            }
            for c in self.collectors
        ]


collector_manager = CollectorManager()
