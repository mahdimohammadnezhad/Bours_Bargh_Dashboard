"""Daily temperature for the price forecast, from Open-Meteo.

Electricity demand in Iran - and with it the power-market price - follows
temperature: the yearly price peak lines up with the summer cooling load
(see docs/DATA_SOURCES.md). There is no single "national temperature", so
this builds one: a population-weighted mean of the daily temperatures of
ten large cities. The weights are approximate city populations (2016
census, thousands) and are a modelling proxy for where electricity is
consumed, not an official statistic. Per-city values are kept in `raw`.

    GET {WEATHER_ARCHIVE_URL}?latitude=..&longitude=..&start_date=&end_date=
        &daily=temperature_2m_mean,temperature_2m_max,temperature_2m_min
        &timezone=Asia/Tehran
        -> one object per location: {"daily": {"time": [...],
           "temperature_2m_mean": [...], ...}}   (ERA5 reanalysis, ~5-day lag)

    GET {WEATHER_FORECAST_URL}?...&past_days=10&forecast_days=16
        -> same shape; days before today are the model's recent analysis,
           later days are forecast.

Verified live 2026-10-11 (both endpoints, multi-location requests). No API
key; free for non-commercial use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import db_write_lock
from app.models.market import WeatherDaily

settings = get_settings()
logger = get_logger(__name__)

LOCATION = "IR_POP_WEIGHTED"
ARCHIVE_SOURCE = "open-meteo:archive"
FORECAST_SOURCE = "open-meteo:forecast"
# Fixed UTC+03:30: Iran dropped daylight saving in 2022, and zoneinfo has no
# tz database on Windows without the extra `tzdata` package.
TEHRAN = timezone(timedelta(hours=3, minutes=30))
# First day of the price history (1398/01/01) minus a margin for the
# trailing temperature averages the forecast uses.
EARLIEST_DAY = date(2019, 3, 1)
ARCHIVE_LAG_DAYS = 6

# (name, latitude, longitude, approximate population in thousands)
CITIES: list[tuple[str, float, float, int]] = [
    ("Tehran", 35.6892, 51.3890, 8694),
    ("Mashhad", 36.2605, 59.6168, 3001),
    ("Isfahan", 32.6546, 51.6680, 1961),
    ("Shiraz", 29.5918, 52.5837, 1565),
    ("Tabriz", 38.0800, 46.2919, 1559),
    ("Qom", 34.6399, 50.8759, 1201),
    ("Ahvaz", 31.3183, 48.6706, 1185),
    ("Kermanshah", 34.3142, 47.0650, 946),
    ("Rasht", 37.2808, 49.5832, 680),
    ("Bandar Abbas", 27.1832, 56.2666, 526),
]

_DAILY_VARS = "temperature_2m_mean,temperature_2m_max,temperature_2m_min"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ElectricityMarketDashboard/1.0; +data-collector)"}


@dataclass(frozen=True)
class WeatherDay:
    day: date
    t_mean: float | None
    t_max: float | None
    t_min: float | None
    per_city: dict[str, float | None]


def tehran_today() -> date:
    return datetime.now(TEHRAN).date()


def _base_params() -> dict[str, str]:
    return {
        "latitude": ",".join(str(c[1]) for c in CITIES),
        "longitude": ",".join(str(c[2]) for c in CITIES),
        "daily": _DAILY_VARS,
        "timezone": "Asia/Tehran",
    }


def _weighted(values: list[float | None]) -> float | None:
    """Population-weighted mean over the cities that have a value."""
    pairs = [(v, c[3]) for v, c in zip(values, CITIES) if v is not None]
    if len(pairs) < len(CITIES) // 2:
        return None  # too few cities reported - don't pass off a partial mean
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total


def combine_locations(payload: Any) -> list[WeatherDay]:
    """Turn Open-Meteo's per-location response into national weighted days."""
    locations = payload if isinstance(payload, list) else [payload]
    if len(locations) != len(CITIES):
        raise ValueError(f"expected {len(CITIES)} locations, got {len(locations)}")

    per_city_series: list[dict[str, dict[str, float | None]]] = []
    for loc in locations:
        daily = loc.get("daily") or {}
        days = daily.get("time") or []
        series: dict[str, dict[str, float | None]] = {}
        for i, d in enumerate(days):
            series[d] = {
                key: (daily.get(f"temperature_2m_{key}") or [None] * len(days))[i]
                for key in ("mean", "max", "min")
            }
        per_city_series.append(series)

    all_days = sorted(set().union(*(s.keys() for s in per_city_series)))
    out: list[WeatherDay] = []
    for d in all_days:
        values = {key: [s.get(d, {}).get(key) for s in per_city_series] for key in ("mean", "max", "min")}
        t_mean = _weighted(values["mean"])
        if t_mean is None:
            continue
        out.append(
            WeatherDay(
                day=date.fromisoformat(d),
                t_mean=round(t_mean, 2),
                t_max=_round(_weighted(values["max"])),
                t_min=_round(_weighted(values["min"])),
                per_city={c[0]: v for c, v in zip(CITIES, values["mean"])},
            )
        )
    return out


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


async def fetch_archive(client: httpx.AsyncClient, start: date, end: date) -> list[WeatherDay]:
    params = {**_base_params(), "start_date": start.isoformat(), "end_date": end.isoformat()}
    response = await client.get(settings.WEATHER_ARCHIVE_URL, params=params, headers=_HEADERS, timeout=120.0)
    response.raise_for_status()
    return combine_locations(response.json())


async def fetch_forecast(client: httpx.AsyncClient, past_days: int = 10, forecast_days: int = 16) -> list[WeatherDay]:
    params = {**_base_params(), "past_days": str(past_days), "forecast_days": str(forecast_days)}
    response = await client.get(settings.WEATHER_FORECAST_URL, params=params, headers=_HEADERS, timeout=60.0)
    response.raise_for_status()
    return combine_locations(response.json())


async def _upsert(session: AsyncSession, days: list[WeatherDay], source: str, today: date) -> int:
    """Insert/update rows. Archive (observed) values always win; forecast-API
    values only fill days that have no archive row yet."""
    if not days:
        return 0
    existing = {
        row.day: row
        for row in (
            await session.execute(
                select(WeatherDaily).where(
                    WeatherDaily.location == LOCATION,
                    WeatherDaily.day >= days[0].day,
                    WeatherDaily.day <= days[-1].day,
                )
            )
        ).scalars()
    }
    written = 0
    for wd in days:
        row = existing.get(wd.day)
        if row is not None and source == FORECAST_SOURCE and row.source == ARCHIVE_SOURCE:
            continue
        if row is None:
            row = WeatherDaily(location=LOCATION, day=wd.day, source=source)
            session.add(row)
        row.t_mean, row.t_max, row.t_min = wd.t_mean, wd.t_max, wd.t_min
        row.is_forecast = wd.day >= today and source == FORECAST_SOURCE
        row.source = source
        row.raw = {"per_city_mean": wd.per_city, "weights": {c[0]: c[3] for c in CITIES}}
        row.fetched_at = datetime.now(timezone.utc)
        written += 1
    return written


async def refresh_weather(session: AsyncSession, client: httpx.AsyncClient) -> dict[str, int]:
    """Fill observed history up to the archive's lag, then the latest forecast.

    Incremental: the archive is only requested from the day after the
    newest archive row, so after the first run this is a few small calls.
    """
    today = tehran_today()
    newest_archive = (
        await session.execute(
            select(WeatherDaily.day)
            .where(WeatherDaily.location == LOCATION, WeatherDaily.source == ARCHIVE_SOURCE)
            .order_by(WeatherDaily.day.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    start = (newest_archive + timedelta(days=1)) if newest_archive else EARLIEST_DAY
    end = today - timedelta(days=ARCHIVE_LAG_DAYS)

    counts = {"archive": 0, "forecast": 0}
    if start <= end:
        archive_days = await fetch_archive(client, start, end)
        async with db_write_lock():
            counts["archive"] = await _upsert(session, archive_days, ARCHIVE_SOURCE, today)
            await session.commit()

    forecast_days = await fetch_forecast(client)
    async with db_write_lock():
        counts["forecast"] = await _upsert(session, forecast_days, FORECAST_SOURCE, today)
        await session.commit()
    logger.info("weather refresh: %s", counts)
    return counts


async def load_temperatures(session: AsyncSession) -> tuple[dict[date, float], set[date]]:
    """All stored national mean temperatures, and which of those days are forecasts."""
    rows = (
        await session.execute(
            select(WeatherDaily.day, WeatherDaily.t_mean, WeatherDaily.is_forecast).where(
                WeatherDaily.location == LOCATION, WeatherDaily.t_mean.is_not(None)
            )
        )
    ).all()
    temps = {r.day: float(r.t_mean) for r in rows}
    forecast_days = {r.day for r in rows if r.is_forecast}
    return temps, forecast_days
