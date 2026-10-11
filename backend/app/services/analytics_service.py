"""Orchestrates the analytics/ package against real stored quotes.

Deliberately conservative: below MIN_POINTS observations, every function
here returns an "insufficient_data" status rather than computing statistics
on a handful of points and presenting them as meaningful - see docs brief
section 47 ("do not fabricate insights") and section 16.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import anomalies as anomaly_detectors
from app.analytics.decision_support import build_insights
from app.analytics.regime import classify_regime
from app.analytics.stats import DescriptiveStats, descriptive_stats, rolling_std
from app.schemas.analytics import (
    AnalyticsOverviewOut,
    AnomaliesOut,
    AnomalyOut,
    DescriptiveStatsOut,
    InsightOut,
    RegimeOut,
)
from app.services.market_service import get_price_history

MIN_POINTS = 20
VOLATILITY_WINDOW = 20
DEFAULT_LOOKBACK_DAYS = 30


def _to_stats_out(stats: DescriptiveStats) -> DescriptiveStatsOut:
    return DescriptiveStatsOut(
        count=stats.count,
        mean=stats.mean,
        median=stats.median,
        minimum=stats.minimum,
        maximum=stats.maximum,
        std_dev=stats.std_dev,
        coefficient_of_variation=stats.coefficient_of_variation,
        p10=stats.p10,
        p25=stats.p25,
        p75=stats.p75,
        p90=stats.p90,
    )


async def _load_series(
    session: AsyncSession,
    source_id: str,
    source_symbol: str,
    lookback_days: int,
) -> tuple[list[datetime], list[float], list[float]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    rows = await get_price_history(session, source_id, source_symbol, start, end)

    timestamps: list[datetime] = []
    prices: list[float] = []
    volumes: list[float] = []
    for row in rows:
        if row.last_price is None:
            continue
        timestamps.append(row.observed_at)
        prices.append(float(row.last_price))
        volumes.append(float(row.volume) if row.volume is not None else 0.0)
    return timestamps, prices, volumes


async def get_overview(
    session: AsyncSession,
    source_id: str,
    source_symbol: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> AnalyticsOverviewOut:
    timestamps, prices, volumes = await _load_series(session, source_id, source_symbol, lookback_days)

    if len(prices) < MIN_POINTS:
        return AnalyticsOverviewOut(
            status="insufficient_data",
            source_id=source_id,
            source_symbol=source_symbol,
            available_points=len(prices),
            min_required_points=MIN_POINTS,
        )

    price_stats = descriptive_stats(prices)
    volume_stats = descriptive_stats(volumes) if any(v > 0 for v in volumes) else None

    vol_series = rolling_std(prices, VOLATILITY_WINDOW)
    volatility_history = [v for v in vol_series if v is not None]
    recent_volatility = volatility_history[-1] if volatility_history else None

    regime = classify_regime(
        price_series=prices,
        volume_series=volumes if volume_stats else None,
        recent_volatility=recent_volatility,
        volatility_history=volatility_history[:-1] if len(volatility_history) > 1 else None,
    )

    lookback_label = f"the last {len(prices)} observations ({lookback_days}-day window)"
    insights = build_insights(prices, volumes if volume_stats else None, lookback_label)

    return AnalyticsOverviewOut(
        status="ok",
        source_id=source_id,
        source_symbol=source_symbol,
        lookback_start=timestamps[0],
        lookback_end=timestamps[-1],
        available_points=len(prices),
        min_required_points=MIN_POINTS,
        price_stats=_to_stats_out(price_stats),
        volume_stats=_to_stats_out(volume_stats) if volume_stats else None,
        regime=RegimeOut(observed=regime.observed, labels=regime.labels, interpretation=regime.interpretation),
        insights=[InsightOut(text=i.text, evidence=i.evidence) for i in insights],
    )


async def get_anomalies(
    session: AsyncSession,
    source_id: str,
    source_symbol: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> AnomaliesOut:
    timestamps, prices, volumes = await _load_series(session, source_id, source_symbol, lookback_days)

    if len(prices) < MIN_POINTS:
        return AnomaliesOut(
            status="insufficient_data",
            source_id=source_id,
            source_symbol=source_symbol,
            available_points=len(prices),
            min_required_points=MIN_POINTS,
        )

    found = anomaly_detectors.detect_all(timestamps, prices, "price", source_id)
    if any(v > 0 for v in volumes):
        found += anomaly_detectors.detect_all(timestamps, volumes, "volume", source_id)
    found.sort(key=lambda a: a.timestamp, reverse=True)

    return AnomaliesOut(
        status="ok",
        source_id=source_id,
        source_symbol=source_symbol,
        available_points=len(prices),
        min_required_points=MIN_POINTS,
        anomalies=[
            AnomalyOut(
                timestamp=a.timestamp,
                metric=a.metric,
                source=a.source,
                method=a.method,
                observed_value=a.observed_value,
                expected_range=a.expected_range,
                severity=a.severity.value,
                explanation=a.explanation,
            )
            for a in found
        ],
    )
