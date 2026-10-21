from datetime import datetime, timedelta, timezone

import pytest

from app.collectors.base import NormalizedQuote
from app.models.market import WeatherDaily
from app.services.historical_ingestion import DAILY_SERIES, POWER_BASELOAD_SYMBOL, SOURCE_ID
from app.services.market_service import upsert_quote
from app.services.weather import ARCHIVE_SOURCE, FORECAST_SOURCE, LOCATION
from tests.test_forecast import synthetic_market

FREE_FORWARD_SYMBOL = DAILY_SERIES["free_forward"].symbol


async def _seed(db_session, symbol: str = POWER_BASELOAD_SYMBOL, keep_days: int | None = None) -> None:
    """keep_days: only the last N calendar days of prices (a young market)."""
    rows, temps, today = synthetic_market()
    if keep_days is not None:
        rows = [r for r in rows if r[0] > today - timedelta(days=keep_days)]
    for d, price, value, kwh in rows:
        await upsert_quote(
            db_session,
            NormalizedQuote(
                source_id=SOURCE_ID,
                source_symbol=symbol,
                observed_at=datetime(d.year, d.month, d.day, tzinfo=timezone.utc),
                last_price=price,
                value=value,
                volume=kwh,
                transaction_count=10,
            ),
        )
    for d, t in temps.items():
        forecast = d > today
        db_session.add(
            WeatherDaily(
                location=LOCATION,
                day=d,
                t_mean=t,
                is_forecast=forecast,
                source=FORECAST_SOURCE if forecast else ARCHIVE_SOURCE,
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/analytics/forecast", "/api/analytics/patterns", "/api/analytics/recommendations"])
async def test_empty_database_reports_insufficient_data(client, path):
    response = await client.get(path)
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"


@pytest.mark.asyncio
async def test_unknown_market_is_rejected(client):
    response = await client.get("/api/analytics/forecast", params={"market": "nonsense"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_main_power_market_forecast_patterns_and_recommendations(client, db_session):
    await _seed(db_session)
    params = {"market": "power"}

    forecast = (await client.get("/api/analytics/forecast", params=params)).json()
    assert forecast["status"] == "ok"
    assert forecast["series"]["symbol"] == POWER_BASELOAD_SYMBOL
    assert forecast["series"]["market"] == "power"
    assert forecast["monthly"]["status"] == "ok"
    assert len(forecast["monthly"]["points"]) == 6
    monthly_models = {s["model"] for s in forecast["monthly"]["validation"]["scores"]}
    assert monthly_models >= {"naive", "drift", "temp_season"}
    assert set(forecast["monthly"]["models"]) == monthly_models  # every model is switchable
    selected = forecast["monthly"]["validation"]["selected_model"]
    assert forecast["monthly"]["models"][selected] == forecast["monthly"]["points"]
    assert forecast["daily"]["status"] == "ok"
    assert set(forecast["daily"]["models"]) == {s["model"] for s in forecast["daily"]["validation"]["scores"]}
    assert forecast["history"] and forecast["temperature"]
    assert any(t["is_forecast"] for t in forecast["temperature"])

    patterns = (await client.get("/api/analytics/patterns", params=params)).json()
    assert patterns["status"] == "ok"
    assert len(patterns["seasonal"]) == 12
    assert patterns["analogues"] and "jalali" in patterns["analogues"][0]

    rec = (await client.get("/api/analytics/recommendations", params=params)).json()
    assert rec["status"] == "ok"
    assert rec["signal"] in {"upward_pressure", "downward_pressure", "mixed"}
    assert rec["evidence"]


@pytest.mark.asyncio
async def test_free_power_is_the_default_and_handles_its_short_history(client, db_session):
    # ~1.5 years of Free Power: a daily forecast and patterns are possible, a
    # validated monthly outlook is not - that must be said, not faked.
    await _seed(db_session, symbol=FREE_FORWARD_SYMBOL, keep_days=560)

    forecast = (await client.get("/api/analytics/forecast")).json()
    assert forecast["series"]["market"] == "free_forward"
    assert forecast["series"]["symbol"] == FREE_FORWARD_SYMBOL
    assert forecast["daily"]["status"] == "ok"
    assert forecast["monthly"]["status"] == "insufficient_data"
    assert forecast["monthly"]["points"] == []

    rec = (await client.get("/api/analytics/recommendations")).json()
    assert rec["status"] == "ok"
    assert "short_history" in rec["caution"]
    assert not any(e["key"].startswith("outlook_") for e in rec["evidence"])
    directional = [e for e in rec["evidence"] if e["direction"] != 0 and e["strength"] > 0]
    if len(directional) < 2:
        assert rec["signal"] == "mixed"  # one vote is not a signal
