"""Runs forecast / patterns / recommendation over the stored series, per market.

Markets (historical_ingestion.DAILY_SERIES): Free Power forward base load
(default - what tsetmc.ir's Free Power tab quotes), physical Free Power, and
the main regulated power market's base load. Inputs are each market's daily
VWAP rows plus the national daily temperatures (weather_daily).

Free Power has only ~1.5 years of history (from 1403/1404), so its
thresholds are lower and its monthly outlook honestly reports
insufficient_data (it needs 3+ years to learn and validate seasonality).

The analysis takes about a second of pure-Python work, so it runs in a
worker thread (never on the event loop that serves the WebSocket) and each
market's result is cached until its inputs change - checked with a cheap
fingerprint on every request.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.forecast import (
    MIN_TRADING_DAYS,
    DailyForecast,
    MonthlyOutlook,
    build_daily_forecast,
    build_monthly_outlook,
)
from app.analytics.patterns import MIN_YEAR_TRADING_DAYS, PatternsResult, build_patterns
from app.analytics.recommendation import Recommendation, build_recommendation
from app.analytics.stats import percentile_rank
from app.models.market import MarketQuote
from app.services.historical_ingestion import DAILY_SERIES, SOURCE_ID
from app.services.weather import load_temperatures, tehran_today

HISTORY_TRADING_DAYS = 120
VOLATILITY_WINDOW = 20


@dataclass(frozen=True)
class MarketConfig:
    key: str
    series_key: str  # key in DAILY_SERIES
    min_trading_days: int
    min_pattern_days: int
    min_year_days: int


MARKETS: dict[str, MarketConfig] = {
    "free_forward": MarketConfig("free_forward", "free_forward", 120, 120, 40),
    "free_physical": MarketConfig("free_physical", "free_physical", 120, 120, 40),
    "power": MarketConfig("power", "power", MIN_TRADING_DAYS, 250, MIN_YEAR_TRADING_DAYS),
}
DEFAULT_MARKET = "free_forward"


@dataclass
class AnalysisBundle:
    market: str
    symbol: str
    fingerprint: tuple
    generated_at: datetime
    today: date
    daily_rows: list[tuple[date, float, float, float]]
    temps: dict[date, float]
    forecast_days: set[date]
    daily: DailyForecast
    monthly: MonthlyOutlook
    patterns: PatternsResult
    recommendation: Recommendation
    volatility_percentile: float | None


_cache: dict[str, AnalysisBundle] = {}
_lock = asyncio.Lock()


async def load_inputs(
    session: AsyncSession, symbol: str
) -> tuple[list[tuple[date, float, float, float]], dict[date, float], set[date]]:
    rows = (
        await session.execute(
            select(MarketQuote.observed_at, MarketQuote.last_price, MarketQuote.value, MarketQuote.volume)
            .where(MarketQuote.source_id == SOURCE_ID, MarketQuote.source_symbol == symbol)
            .order_by(MarketQuote.observed_at)
        )
    ).all()
    daily = [
        (r.observed_at.date(), float(r.last_price), float(r.value or 0), float(r.volume or 0))
        for r in rows
        if r.last_price is not None and float(r.last_price) > 0
    ]
    temps, forecast_days = await load_temperatures(session)
    return daily, temps, forecast_days


def _volatility_percentile(prices: list[float]) -> float | None:
    if len(prices) < VOLATILITY_WINDOW * 3:
        return None
    logp = [math.log(p) for p in prices]
    returns = [b - a for a, b in zip(logp, logp[1:])]
    vols = [statistics.pstdev(returns[i - VOLATILITY_WINDOW : i]) for i in range(VOLATILITY_WINDOW, len(returns) + 1)]
    return percentile_rank(vols[-1], vols)


def analyse(
    daily: list[tuple[date, float, float, float]],
    temps: dict[date, float],
    forecast_days: set[date],
    today: date,
    fingerprint: tuple = (),
    market: str = "power",
) -> AnalysisBundle:
    config = MARKETS[market]
    prices = [(d, p) for d, p, _, _ in daily]
    daily_forecast = build_daily_forecast(prices, temps, min_trading_days=config.min_trading_days)
    monthly = build_monthly_outlook(daily, temps, forecast_days, today)
    patterns = build_patterns(daily, temps, today, min_days=config.min_pattern_days, min_year_days=config.min_year_days)
    volatility_percentile = _volatility_percentile([p for _, p in prices])
    recommendation = build_recommendation(monthly, daily_forecast, patterns, volatility_percentile)
    return AnalysisBundle(
        market=market,
        symbol=DAILY_SERIES[config.series_key].symbol,
        fingerprint=fingerprint,
        generated_at=datetime.now(timezone.utc),
        today=today,
        daily_rows=daily,
        temps=temps,
        forecast_days=forecast_days,
        daily=daily_forecast,
        monthly=monthly,
        patterns=patterns,
        recommendation=recommendation,
        volatility_percentile=volatility_percentile,
    )


async def get_analysis(session: AsyncSession, market: str = DEFAULT_MARKET) -> AnalysisBundle:
    config = MARKETS[market]
    daily, temps, forecast_days = await load_inputs(session, DAILY_SERIES[config.series_key].symbol)
    today = tehran_today()
    fingerprint = (
        today,
        len(daily),
        daily[-1] if daily else None,
        len(temps),
        round(sum(temps.values()), 2),
        len(forecast_days),
    )
    cached = _cache.get(market)
    if cached is not None and cached.fingerprint == fingerprint:
        return cached
    async with _lock:
        cached = _cache.get(market)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached
        bundle = await asyncio.to_thread(analyse, daily, temps, forecast_days, today, fingerprint, market)
        _cache[market] = bundle
        return bundle
