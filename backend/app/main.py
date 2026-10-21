import asyncio
from contextlib import asynccontextmanager

import httpx
import jdatetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api import routes_analytics, routes_health, routes_history, routes_market, ws
from app.cache.redis_client import cache
from app.collectors.manager import collector_manager
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.database.session import SessionLocal, init_db
from app.models.market import MarketQuote
from app.services.historical_ingestion import (
    DAILY_SERIES,
    backfill_daily_series,
    backfill_iee_derivative_free_power_history,
    backfill_iee_monthly_prices,
)
from app.services.historical_ingestion import SOURCE_ID as HISTORICAL_SOURCE_ID
from app.services.weather import refresh_weather

settings = get_settings()
setup_logging(settings.LOG_LEVEL)
logger = get_logger(__name__)

_background_tasks: set[asyncio.Task] = set()


async def maybe_run_historical_backfill() -> None:
    """Re-run the historical backfills in the background on every startup.

    Both are idempotent upserts costing a handful of requests (one per
    Jalali year for the monthly report, one for the derivative history),
    so re-running is cheap - and it is what fills the gap after the app
    (or its network route to the sources) has been down for a while. An
    earlier run-once marker meant a month offline was never backfilled.
    Fire-and-forget so this never delays the app becoming ready; failures
    are logged, not raised. Monkeypatched to a noop in tests (see
    tests/conftest.py) so the test suite never makes real network calls.
    """

    async def _run() -> None:
        try:
            async with httpx.AsyncClient() as client, SessionLocal() as session:
                written = await backfill_iee_monthly_prices(session, client, settings.IEE_NEW_BASE_URL)
                logger.info("historical backfill complete: %d monthly quotes", written)
                written = await backfill_iee_derivative_free_power_history(session, client, settings.IEE_NEW_BASE_URL)
                logger.info("historical backfill complete: %d derivative-free-power history quotes", written)
        except Exception as exc:  # noqa: BLE001 - background task, must not crash the app
            logger.warning("historical backfill failed: %s", exc)
        # Then keep the forecast's inputs (daily price history + temperatures)
        # fresh for as long as the app runs.
        while True:
            await refresh_forecast_inputs()
            await asyncio.sleep(settings.FORECAST_REFRESH_HOURS * 3600)

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def refresh_forecast_inputs() -> None:
    """Daily price history for each forecast market (DAILY_SERIES: main power
    base load, Free Power forward base load, physical Free Power): the full
    history the first time, then only from the latest stored Jalali year
    (one request per series). Weather:
    incremental archive + the latest 16-day forecast. Each part fails
    independently and is retried at the next refresh."""
    async with httpx.AsyncClient(follow_redirects=True) as client, SessionLocal() as session:
        for series in DAILY_SERIES.values():
            try:
                latest = (
                    await session.execute(
                        select(func.max(MarketQuote.observed_at)).where(
                            MarketQuote.source_id == HISTORICAL_SOURCE_ID,
                            MarketQuote.source_symbol == series.symbol,
                        )
                    )
                ).scalar_one_or_none()
                start_year = jdatetime.date.fromgregorian(date=latest.date()).year if latest else None
                written = await backfill_daily_series(session, client, settings.IEE_NEW_BASE_URL, series, start_year)
                logger.info("forecast inputs: %s - %d trading days upserted", series.symbol, written)
            except Exception as exc:  # noqa: BLE001 - background refresh, must not crash the app
                logger.warning("forecast inputs: %s refresh failed: %r", series.symbol, exc)
        try:
            await refresh_weather(session, client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("forecast inputs: weather refresh failed: %r", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s (env=%s)", settings.APP_NAME, settings.ENV)
    await cache.connect()
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        logger.error("Database initialization failed - API will run in degraded mode: %s", exc)
    await collector_manager.start()
    await maybe_run_historical_backfill()
    yield
    await collector_manager.stop()
    await cache.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE)

app.include_router(routes_health.router)
app.include_router(routes_market.router)
app.include_router(routes_history.router)
app.include_router(routes_analytics.router)
app.include_router(ws.router)


@app.get("/")
async def root() -> dict:
    return {"name": settings.APP_NAME, "status": "running", "docs": "/docs"}
