import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


@dataclass
class NormalizedQuote:
    source_id: str
    source_symbol: str
    observed_at: datetime
    last_price: float | None = None
    close_price: float | None = None
    price_change: float | None = None
    price_change_percent: float | None = None
    volume: float | None = None
    value: float | None = None
    transaction_count: int | None = None
    raw: dict | None = None

    def is_valid(self) -> bool:
        """Baseline sanity checks. Never trust a parsed record blindly."""
        if self.last_price is not None and self.last_price < 0:
            return False
        if self.volume is not None and self.volume < 0:
            return False
        now = datetime.now(timezone.utc)
        observed = self.observed_at if self.observed_at.tzinfo else self.observed_at.replace(tzinfo=timezone.utc)
        if observed > now.replace(microsecond=0) and (observed - now).total_seconds() > 300:
            return False  # implausibly far in the future
        return True


@dataclass
class CollectorState:
    status: str = "unknown"  # healthy | degraded | down | not_configured
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    circuit_open_until: datetime | None = None
    current_interval: float = settings.POLL_INTERVAL_ACTIVE
    last_latency_ms: float | None = None
    # source_symbol -> (observed_at, fingerprint) of the newest quote
    # persisted for it, so a re-observed but unchanged quote isn't stored
    # or broadcast again (see market_service.record_cycle).
    last_persisted: dict[str, tuple[datetime, str]] = field(default_factory=dict)


@dataclass
class CycleResult:
    status: str  # success | error | skipped | not_configured
    quotes: list[NormalizedQuote] = field(default_factory=list)
    http_status: int | None = None
    latency_ms: float | None = None
    error_message: str | None = None


class BaseCollector(ABC):
    source_id: str
    name: str
    base_url: str
    configured: bool = True
    # Per-source lower bound on the poll interval, for sources that throttle
    # more aggressively than POLL_INTERVAL_ACTIVE allows.
    min_poll_interval: float = 0.0

    def __init__(self) -> None:
        self.state = CollectorState(current_interval=settings.POLL_INTERVAL_ACTIVE)
        if not self.configured:
            self.state.status = "not_configured"

    @abstractmethod
    async def fetch_raw(self, client: httpx.AsyncClient) -> object:
        """Perform the HTTP call(s) for one polling cycle and return the raw payload."""

    @abstractmethod
    def parse(self, raw: object) -> list[NormalizedQuote]:
        """Turn a raw payload into normalized quotes. Must not raise on a single bad field."""

    def _circuit_is_open(self) -> bool:
        if self.state.circuit_open_until is None:
            return False
        return datetime.now(timezone.utc) < self.state.circuit_open_until

    async def run_cycle(self, client: httpx.AsyncClient) -> CycleResult:
        if not self.configured:
            return CycleResult(status="not_configured")

        if self._circuit_is_open():
            return CycleResult(status="skipped", error_message="circuit breaker open")

        started = datetime.now(timezone.utc)
        last_exc: Exception | None = None
        raw = None
        http_status = None

        for attempt in range(settings.MAX_RETRIES):
            try:
                raw = await self.fetch_raw(client)
                http_status = 200
                break
            except httpx.HTTPStatusError as exc:
                http_status = exc.response.status_code
                last_exc = exc
                if http_status == 429:
                    retry_after = exc.response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else self._backoff_delay(attempt)
                    logger.warning("%s got 429, backing off %.1fs", self.source_id, delay)
                    await asyncio.sleep(delay)
                    continue
                if http_status == 403:
                    logger.warning("%s got 403 - marking degraded, will slow down", self.source_id)
                    break
                if 500 <= http_status < 600:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                break
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                last_exc = exc
                await asyncio.sleep(self._backoff_delay(attempt))
                continue
            except Exception as exc:  # noqa: BLE001 - a collector must never crash the manager
                last_exc = exc
                break

        latency_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        self.state.last_latency_ms = latency_ms

        if raw is None:
            self._record_failure(last_exc, http_status)
            return CycleResult(
                status="error",
                http_status=http_status,
                latency_ms=latency_ms,
                error_message=str(last_exc) if last_exc else "unknown error",
            )

        try:
            quotes = [q for q in self.parse(raw) if q.is_valid()]
        except Exception as exc:  # noqa: BLE001
            self._record_failure(exc, http_status)
            return CycleResult(status="error", http_status=http_status, latency_ms=latency_ms, error_message=str(exc))

        self._record_success()
        return CycleResult(status="success", quotes=quotes, http_status=http_status, latency_ms=latency_ms)

    def _backoff_delay(self, attempt: int) -> float:
        base = settings.BACKOFF_BASE_SECONDS * (2**attempt)
        capped = min(base, settings.BACKOFF_MAX_SECONDS)
        return capped + random.uniform(0, capped * 0.1)

    def _record_success(self) -> None:
        self.state.status = "healthy"
        self.state.consecutive_failures = 0
        self.state.last_success_at = datetime.now(timezone.utc)
        self.state.circuit_open_until = None
        self.state.current_interval = settings.POLL_INTERVAL_ACTIVE

    def _record_failure(self, exc: Exception | None, http_status: int | None) -> None:
        self.state.consecutive_failures += 1
        self.state.last_error = str(exc) if exc else f"HTTP {http_status}"
        self.state.last_error_at = datetime.now(timezone.utc)

        if http_status == 403:
            self.state.status = "degraded"
        elif self.state.consecutive_failures >= settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            self.state.status = "down"
            self.state.circuit_open_until = datetime.now(timezone.utc) + timedelta(
                seconds=settings.CIRCUIT_BREAKER_COOLDOWN_SECONDS
            )
            logger.error(
                "%s circuit breaker OPEN after %d consecutive failures, cooling down %.0fs",
                self.source_id,
                self.state.consecutive_failures,
                settings.CIRCUIT_BREAKER_COOLDOWN_SECONDS,
            )
        else:
            self.state.status = "degraded"

        self.state.current_interval = min(
            settings.POLL_INTERVAL_IDLE,
            settings.POLL_INTERVAL_ACTIVE * (2**self.state.consecutive_failures),
        )
