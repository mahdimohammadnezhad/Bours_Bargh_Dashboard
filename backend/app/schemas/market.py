from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    source_symbol: str
    instrument_symbol: str | None = None
    observed_at: datetime
    last_price: float | None = None
    close_price: float | None = None
    price_change: float | None = None
    price_change_percent: float | None = None
    volume: float | None = None
    value: float | None = None
    transaction_count: int | None = None
    is_stale: bool = False
    # Collector-specific context that doesn't have its own column (contract
    # name, market-state text, etc.) - see MarketQuote.raw. Frontend uses
    # this for display only, never for calculations.
    raw: dict[str, Any] | None = None


class SourceHealthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    name: str
    status: str
    last_success_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    consecutive_failures: int = 0
    latency_ms: float | None = None
    stale_seconds: float | None = None


class CollectorLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    http_status: int | None = None
    latency_ms: float | None = None
    records_fetched: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    error_message: str | None = None


class MarketStatusOut(BaseModel):
    is_active_session: bool
    server_time: datetime
    sources: list[SourceHealthOut]


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    market_segment: str | None = None


class PriceHistoryPoint(BaseModel):
    observed_at: datetime
    last_price: float | None = None
    volume: float | None = None
    raw: dict[str, Any] | None = None


class PriceHistoryOut(BaseModel):
    source_id: str
    source_symbol: str
    points: list[PriceHistoryPoint]
