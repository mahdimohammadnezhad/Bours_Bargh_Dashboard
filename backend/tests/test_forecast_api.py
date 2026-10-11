from datetime import datetime, timezone

import pytest

from app.collectors.base import NormalizedQuote
from app.models.market import WeatherDaily
from app.services.historical_ingestion import POWER_BASELOAD_SYMBOL, SOURCE_ID
from app.services.market_service import upsert_quote
from app.services.weather import ARCHIVE_SOURCE, FORECAST_SOURCE, LOCATION
from tests.test_forecast import synthetic_market


async def _seed(db_session) -> None:
    rows, temps, today = synthetic_market()
    for d, price, value, kwh in rows:
        await upsert_quote(
            db_session,
            NormalizedQuote(
                source_id=SOURCE_ID,
                source_symbol=POWER_BASELOAD_SYMBOL,
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
async def test_forecast_patterns_and_recommendations_from_stored_series(client, db_session):
    await _seed(db_session)

    forecast = (await client.get("/api/analytics/forecast")).json()
    assert forecast["status"] == "ok"
    assert forecast["series"]["symbol"] == POWER_BASELOAD_SYMBOL
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

    patterns = (await client.get("/api/analytics/patterns")).json()
    assert patterns["status"] == "ok"
    assert len(patterns["seasonal"]) == 12
    assert patterns["analogues"] and "jalali" in patterns["analogues"][0]

    rec = (await client.get("/api/analytics/recommendations")).json()
    assert rec["status"] == "ok"
    assert rec["signal"] in {"upward_pressure", "downward_pressure", "mixed"}
    assert rec["evidence"]
