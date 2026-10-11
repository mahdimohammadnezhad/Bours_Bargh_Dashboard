"""Runs forecast / patterns / recommendation over the stored series.

Inputs: the daily base-load VWAP rows (historical_ingestion.POWER_BASELOAD_SYMBOL)
and the national daily temperatures (weather_daily). The analysis takes
about a second of pure-Python work, so it runs in a worker thread (never on
the event loop that serves the WebSocket) and its result is cached until
the inputs change - checked with a cheap fingerprint on every request.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.forecast import DailyForecast, MonthlyOutlook, build_daily_forecast, build_monthly_outlook
from app.analytics.patterns import PatternsResult, build_patterns
from app.analytics.recommendation import Recommendation, build_recommendation
from app.analytics.stats import percentile_rank
from app.models.market import MarketQuote
from app.services.historical_ingestion import POWER_BASELOAD_SYMBOL, SOURCE_ID
from app.services.weather import load_temperatures, tehran_today

HISTORY_TRADING_DAYS = 120
VOLATILITY_WINDOW = 20


@dataclass
class AnalysisBundle:
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


_cache: AnalysisBundle | None = None
_lock = asyncio.Lock()


async def load_inputs(session: AsyncSession) -> tuple[list[tuple[date, float, float, float]], dict[date, float], set[date]]:
    rows = (
        await session.execute(
            select(MarketQuote.observed_at, MarketQuote.last_price, MarketQuote.value, MarketQuote.volume)
            .where(MarketQuote.source_id == SOURCE_ID, MarketQuote.source_symbol == POWER_BASELOAD_SYMBOL)
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
) -> AnalysisBundle:
    prices = [(d, p) for d, p, _, _ in daily]
    daily_forecast = build_daily_forecast(prices, temps)
    monthly = build_monthly_outlook(daily, temps, forecast_days, today)
    patterns = build_patterns(daily, temps, today)
    volatility_percentile = _volatility_percentile([p for _, p in prices])
    recommendation = build_recommendation(monthly, daily_forecast, patterns, volatility_percentile)
    return AnalysisBundle(
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


async def get_analysis(session: AsyncSession) -> AnalysisBundle:
    global _cache
    daily, temps, forecast_days = await load_inputs(session)
    today = tehran_today()
    fingerprint = (
        today,
        len(daily),
        daily[-1] if daily else None,
        len(temps),
        round(sum(temps.values()), 2),
        len(forecast_days),
    )
    if _cache is not None and _cache.fingerprint == fingerprint:
        return _cache
    async with _lock:
        if _cache is not None and _cache.fingerprint == fingerprint:
            return _cache
        _cache = await asyncio.to_thread(analyse, daily, temps, forecast_days, today, fingerprint)
        return _cache
