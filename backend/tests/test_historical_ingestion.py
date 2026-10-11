from datetime import datetime, timedelta, timezone

import httpx
import jdatetime
import pytest
import respx

from app.services.historical_ingestion import (
    DERIVATIVE_FREE_STATS_PATH,
    MONTHLY_PRICE_PATH,
    _last_day_of_jalali_month_utc,
    _parse_jalali_date_utc,
    backfill_iee_derivative_free_power_history,
    backfill_iee_monthly_prices,
    fetch_derivative_free_power_statistics,
    fetch_monthly_prices,
    parse_derivative_free_power_statistics,
    parse_monthly_prices,
)
from app.services.market_service import get_price_history


@pytest.fixture(autouse=True)
def _no_request_spacing(monkeypatch):
    # The real pause protects IEE from bursts; mocked HTTP doesn't need it.
    monkeypatch.setattr("app.services.historical_ingestion.IEE_REQUEST_SPACING_SECONDS", 0)

# Trimmed to 2 of the 261 rows seen live on 2026-09-05 from
# https://webapi.iee.ir/api/PowerMarket/GetDerivativeFreePowerMarketStatistics
SAMPLE_DERIVATIVE_FREE_STATS = {
    "results": [
        {
            "date": "1405/06/14",
            "energySymbol": "DDP00PFBEXW050621",
            "contract": "بارپايه هفتگي 14050621",
            "avgPrice": "59000",
            "maxPrice": "59,000",
            "minPrice": "59,000",
            "tradeNo": "2",
            "tradeVolumeTooltip": "300",
            "closingPrice": "59,000",
            "tradeValue": "2,973,600,000",
            "kiloWattHours": "50,400",
        },
        {
            "date": "1404/01/27",
            "energySymbol": "DDP00PFBEXM040201",
            "contract": "بارپايه ماهانه 14040201",
            "avgPrice": "63600",
            "maxPrice": "64,000",
            "minPrice": "62,000",
            "tradeNo": "4",
            "tradeVolumeTooltip": "5,000",
            "closingPrice": "63,600",
            "tradeValue": "236,592,000,000",
            "kiloWattHours": "3,720,000",
        },
    ],
    "isSuccess": True,
    "pagedMetaData": [{"totalCount": 261}],
}

# Shaped like a real response captured live on 2026-08-30 from
# POST https://webapi.iee.ir/api/Report/GetPowerMarketMonthlyPrice
# body {"Year": 1405, "Months": [1..12]} - see docs/DATA_SOURCES.md.
SAMPLE_MONTHLY_RESPONSE = {
    "results": [
        {
            "year": 1405,
            "month": 5,
            "firstSignboardBaseLoadMidPrice": "3459",
            "greenSignboardBaseLoadMaxPrice": None,
            "greenSignboardBaseLoadMidPrice": "134811",
            "freeSignboardBaseLoadMidPrice": "118933",
            "greenPowerMaxPrice": "169,500",
        },
        {
            # A month with no market activity - fields genuinely blank, not
            # a parsing failure. Must not crash the batch or invent a price.
            "year": 1405,
            "month": 6,
            "firstSignboardBaseLoadMidPrice": "",
            "greenSignboardBaseLoadMidPrice": "",
            "freeSignboardBaseLoadMidPrice": None,
        },
    ],
    "isSuccess": True,
    "isFailed": False,
}


class TestJalaliDateConversion:
    def test_last_day_of_ordinary_month(self):
        # 1405/05 (Mordad) has 31 days -> 1405-05-31 -> 2026-08-22 Gregorian.
        result = _last_day_of_jalali_month_utc(1405, 5)
        assert result == datetime(2026, 8, 22, tzinfo=timezone.utc)

    def test_december_rolls_into_next_jalali_year(self):
        # Esfand (month 12) of a non-leap year has 29 days.
        result = _last_day_of_jalali_month_utc(1404, 12)
        assert result == datetime(2026, 3, 20, tzinfo=timezone.utc)
        assert result.tzinfo is timezone.utc


class TestParseMonthlyPrices:
    def test_parses_all_three_segments_for_a_populated_month(self):
        quotes = parse_monthly_prices(SAMPLE_MONTHLY_RESPONSE["results"])
        by_symbol = {q.source_symbol: q for q in quotes if q.observed_at.month == 8}

        assert by_symbol["IEE_POWER_BASE_MONTHLY"].last_price == 3459.0
        assert by_symbol["IEE_GREEN_BASE_MONTHLY"].last_price == 134811.0
        assert by_symbol["IEE_FREE_BASE_MONTHLY"].last_price == 118933.0
        assert all(q.source_id == "iee_new" for q in quotes)

    def test_skips_blank_fields_without_crashing(self):
        quotes = parse_monthly_prices(SAMPLE_MONTHLY_RESPONSE["results"])
        # Month 6 in the fixture has no usable price in any segment - only
        # the 3 populated fields from month 5 should produce a quote.
        assert len(quotes) == 3
        month_6_date = _last_day_of_jalali_month_utc(1405, 6)
        assert not any(q.observed_at == month_6_date for q in quotes)

    def test_zero_price_months_are_not_stored_as_prices(self):
        # Live 1402 rows carry "0" for months with no published average.
        rows = [{"year": 1402, "month": 1, "firstSignboardBaseLoadMidPrice": "0",
                 "greenSignboardBaseLoadMidPrice": "0", "freeSignboardBaseLoadMidPrice": "0"}]
        assert parse_monthly_prices(rows) == []

    def test_empty_results_returns_empty_list(self):
        assert parse_monthly_prices([]) == []

    def test_non_dict_rows_are_skipped(self):
        assert parse_monthly_prices([None, "not a dict", 42]) == []


@pytest.mark.asyncio
async def test_fetch_monthly_prices_uses_mocked_http(respx_mock):
    respx_mock.post(f"https://webapi.iee.ir/api{MONTHLY_PRICE_PATH}").mock(
        return_value=httpx.Response(200, json=SAMPLE_MONTHLY_RESPONSE)
    )
    async with httpx.AsyncClient() as client:
        rows = await fetch_monthly_prices(client, "https://webapi.iee.ir/api", 1405)
    assert rows == SAMPLE_MONTHLY_RESPONSE["results"]


@pytest.mark.asyncio
async def test_fetch_monthly_prices_sends_jalali_year_and_all_months(respx_mock):
    route = respx_mock.post(f"https://webapi.iee.ir/api{MONTHLY_PRICE_PATH}").mock(
        return_value=httpx.Response(200, json={"results": [], "isSuccess": True})
    )
    async with httpx.AsyncClient() as client:
        await fetch_monthly_prices(client, "https://webapi.iee.ir/api", 1403)

    sent_body = route.calls[0].request.content
    import json

    assert json.loads(sent_body) == {"Year": 1403, "Months": list(range(1, 13))}


@pytest.mark.asyncio
async def test_backfill_writes_and_is_idempotent_on_rerun(db_session, respx_mock):
    respx_mock.post(f"https://webapi.iee.ir/api{MONTHLY_PRICE_PATH}").mock(
        return_value=httpx.Response(200, json=SAMPLE_MONTHLY_RESPONSE)
    )

    async with httpx.AsyncClient() as client:
        written_first = await backfill_iee_monthly_prices(
            db_session, client, "https://webapi.iee.ir/api", start_jalali_year=1405, end_jalali_year=1405
        )
        written_second = await backfill_iee_monthly_prices(
            db_session, client, "https://webapi.iee.ir/api", start_jalali_year=1405, end_jalali_year=1405
        )

    assert written_first == 3
    assert written_second == 3  # re-fetched and re-upserted, not appended

    rows = await get_price_history(
        db_session,
        "iee_new",
        "IEE_POWER_BASE_MONTHLY",
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    assert len(rows) == 1  # not 2 - the second run updated the existing row, didn't duplicate it
    assert float(rows[0].last_price) == 3459.0


class TestJalaliDateStringParsing:
    def test_parses_yyyy_mm_dd(self):
        result = _parse_jalali_date_utc("1405/06/14")
        assert result == datetime(2026, 9, 5, tzinfo=timezone.utc)

    def test_rejects_malformed_string(self):
        assert _parse_jalali_date_utc("not-a-date") is None
        assert _parse_jalali_date_utc("1405/06") is None
        assert _parse_jalali_date_utc(None) is None


class TestParseDerivativeFreePowerStatistics:
    def test_parses_rows_using_energy_symbol_as_source_symbol(self):
        quotes = parse_derivative_free_power_statistics(SAMPLE_DERIVATIVE_FREE_STATS["results"])
        by_symbol = {q.source_symbol: q for q in quotes}

        first = by_symbol["DDP00PFBEXW050621"]
        assert first.source_id == "iee_new"
        assert first.last_price == 59000.0  # from comma-formatted closingPrice
        assert first.volume == 300.0
        assert first.value == 2973600000.0
        assert first.transaction_count == 2
        assert first.observed_at == datetime(2026, 9, 5, tzinfo=timezone.utc)

        second = by_symbol["DDP00PFBEXM040201"]
        assert second.observed_at.year == 2025  # 1404/01/27 Jalali

    def test_days_without_trades_are_skipped(self):
        # Shaped like a live 2026-10-11 row: no trades, placeholder price.
        no_trade = {"date": "1405/06/14", "energySymbol": "DDP00PFBEXM050701", "contract": "بارپايه ماهانه 14050701",
                    "tradeNo": "0", "tradeVolumeTooltip": "0", "closingPrice": "1", "tradeValue": "0"}
        quotes = parse_derivative_free_power_statistics(SAMPLE_DERIVATIVE_FREE_STATS["results"] + [no_trade])
        assert "DDP00PFBEXM050701" not in {q.source_symbol for q in quotes}
        assert len(quotes) == len(SAMPLE_DERIVATIVE_FREE_STATS["results"])

    def test_rows_missing_symbol_or_date_are_skipped(self):
        broken = [{"energySymbol": None, "date": "1405/06/14", "closingPrice": "1"}, {"energySymbol": "X", "date": None}]
        assert parse_derivative_free_power_statistics(broken) == []

    def test_empty_results_returns_empty_list(self):
        assert parse_derivative_free_power_statistics([]) == []


@pytest.mark.asyncio
async def test_fetch_derivative_free_power_statistics_uses_mocked_http(respx_mock):
    respx_mock.get(f"https://webapi.iee.ir/api{DERIVATIVE_FREE_STATS_PATH}").mock(
        return_value=httpx.Response(200, json=SAMPLE_DERIVATIVE_FREE_STATS)
    )
    async with httpx.AsyncClient() as client:
        rows = await fetch_derivative_free_power_statistics(client, "https://webapi.iee.ir/api")
    assert rows == SAMPLE_DERIVATIVE_FREE_STATS["results"]


@pytest.mark.asyncio
async def test_backfill_derivative_free_power_history_requests_one_jalali_year_per_call(db_session, respx_mock):
    # Regression: a single whole-history request (FromDate=1390/01/01) began
    # failing server-side with HTTP 400 after ~32s; year windows work.
    route = respx_mock.get(f"https://webapi.iee.ir/api{DERIVATIVE_FREE_STATS_PATH}").mock(
        return_value=httpx.Response(200, json={"results": [], "isSuccess": True})
    )
    async with httpx.AsyncClient() as client:
        await backfill_iee_derivative_free_power_history(
            db_session, client, "https://webapi.iee.ir/api", start_jalali_year=1403, end_jalali_year=1404
        )

    windows = [(c.request.url.params["FromDate"], c.request.url.params["ToDate"]) for c in route.calls]
    last_day_1403 = (jdatetime.date(1404, 1, 1) - timedelta(days=1)).strftime("%Y/%m/%d")
    last_day_1404 = (jdatetime.date(1405, 1, 1) - timedelta(days=1)).strftime("%Y/%m/%d")
    assert windows == [("1403/01/01", last_day_1403), ("1404/01/01", last_day_1404)]


@pytest.mark.asyncio
async def test_backfill_derivative_free_power_history_is_idempotent(db_session, respx_mock):
    respx_mock.get(f"https://webapi.iee.ir/api{DERIVATIVE_FREE_STATS_PATH}").mock(
        return_value=httpx.Response(200, json=SAMPLE_DERIVATIVE_FREE_STATS)
    )

    async with httpx.AsyncClient() as client:
        # One year only: the mock answers every window with the same rows.
        written_first = await backfill_iee_derivative_free_power_history(
            db_session, client, "https://webapi.iee.ir/api", start_jalali_year=1405, end_jalali_year=1405
        )
        written_second = await backfill_iee_derivative_free_power_history(
            db_session, client, "https://webapi.iee.ir/api", start_jalali_year=1405, end_jalali_year=1405
        )

    assert written_first == 2
    assert written_second == 2

    rows = await get_price_history(
        db_session,
        "iee_new",
        "DDP00PFBEXW050621",
        datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    assert len(rows) == 1  # upserted, not duplicated
    assert float(rows[0].last_price) == 59000.0
