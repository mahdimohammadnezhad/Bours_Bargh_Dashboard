from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.collectors.base import BaseCollector, NormalizedQuote
from app.collectors.iee_new_collector import IEENewCollector
from app.collectors.iee_old_collector import IEEOldCollector
from app.collectors.tsetmc_collector import TSETMCCollector
from app.services.market_service import quote_fingerprint

# Shaped exactly like real responses captured live on 2026-09-05 from
# tsetmc.ir's "بورس انرژی ایران" > "برق آزاد" tab via Playwright network
# capture (not guessed - see docs/DATA_SOURCES.md) - mocks used only in
# tests, per project rule that mock data is never allowed in production
# code paths.
# Live capture 2026-10-21 (tsetmc.ir showed: physical 95.982 B, 3 trades,
# forward 0, total 95.982 B).
SAMPLE_OVERVIEW = {
    "powerOverview": {
        "totalCount": 3,
        "totalValue": 95981760000.0,
        "mazadCount": 0,
        "mazadValue": 0.0,
        "f60_MarketActivityQTotCap": 0.0,
        "dggPlus60_MarketActivityQTotCap": 95981760000.0,
        "f60_MarketActivityZTotTran": 0.0,
        "marketStateTitle": "بسته",
    }
}
SAMPLE_DEMAND = {
    "bestLimitsTop": [
        {
            "insCode": "24591292296063193",
            "title": "بارپايه هفتگي 14050621",
            "powerInstrumentDate": {"loadType": 0, "energySymbol": "DDP00PFBEXW050621"},
            "val": 16800000000.00,
            "qTitMeDem": 2000,
            "zOrdMeDem": 1,
            "pMeDem": 50000.000,
            "pMeOf": 0.0,
            "zOrdMeOf": 0,
            "qTitMeOf": 0,
        }
    ]
}
SAMPLE_SUPPLY = {
    "bestLimitsTop": [
        {
            "insCode": "25228469814401417",
            "title": "بارپايه ماهانه 14050701",
            "powerInstrumentDate": {"loadType": 0, "energySymbol": "DDP00PFBEXM050701"},
            "val": 448200000000.00,
            "qTitMeDem": 0,
            "zOrdMeDem": 0,
            "pMeDem": 0.0,
            "pMeOf": 50000.000,
            "zOrdMeOf": 4,
            "qTitMeOf": 12450,
        },
        {
            "insCode": "12294662990767012",
            "title": "بارپايه ماهانه 14050801",
            "powerInstrumentDate": {"loadType": 0, "energySymbol": "DDP00PFBEXM050801"},
            "val": 63000000000.00,
            "qTitMeDem": 0,
            "zOrdMeDem": 0,
            "pMeDem": 0.0,
            "pMeOf": 50000.000,
            "zOrdMeOf": 1,
            "qTitMeOf": 1750,
        },
    ]
}
SAMPLE_CONTRACTS = {
    "24591292296063193": {
        "closingPriceInfo": {
            "pClosing": 59000.00,
            "pDrCotVal": 59000.00,
            "zTotTran": 2.0,
            "qTotTran5J": 300.0,
            "qTotCap": 2973600000.00,
        }
    }
}
SAMPLE_DAILY_HISTORY = {
    "24591292296063193": {
        "closingPriceDaily": [
            {
                "dEven": 20260902,
                "pClosing": 59500.00,
                "pDrCotVal": 59500.00,
                "priceChange": 904.00,
                "zTotTran": 1.0,
                "qTotTran5J": 500.0,
                "qTotCap": 29750000.00,
            },
            {
                "dEven": 20260901,
                "pClosing": 58596.00,
                "pDrCotVal": 58000.00,
                "priceChange": -21000.00,
                "zTotTran": 2.0,
                "qTotTran5J": 1000.0,
                "qTotCap": 58596000.00,
            },
        ]
    }
}
SAMPLE_TSETMC_RAW = {
    "overview": SAMPLE_OVERVIEW,
    "demand": SAMPLE_DEMAND,
    "supply": SAMPLE_SUPPLY,
    "contracts": SAMPLE_CONTRACTS,
    "daily_history": SAMPLE_DAILY_HISTORY,
}


class TestTSETMCCollectorParse:
    def test_parses_free_power_overview(self):
        collector = TSETMCCollector()
        quotes = collector.parse(SAMPLE_TSETMC_RAW)
        overview = next(q for q in quotes if q.source_symbol == "TSETMC_FREE_POWER_OVERVIEW")
        # The site's "ارزش کل معاملات برق آزاد" (physical + forward).
        assert overview.value == 95981760000.0
        assert overview.transaction_count == 3
        assert overview.raw["marketStateTitle"] == "بسته"

    def test_overview_total_counts_forward_trades_too(self):
        # Live capture 2026-10-11: all trades were forward ("سلف"), none physical.
        forward_day = {
            "powerOverview": {
                **SAMPLE_OVERVIEW["powerOverview"],
                "totalCount": 0,
                "totalValue": 0.0,
                "f60_MarketActivityQTotCap": 265090356000.0,
                "dggPlus60_MarketActivityQTotCap": 265090356000.0,
                "f60_MarketActivityZTotTran": 7.0,
            }
        }
        overview = TSETMCCollector()._parse_overview(forward_day)
        assert overview.value == 265090356000.0
        assert overview.transaction_count == 7

    def test_missing_order_book_levels_become_explicit_empty_rows(self):
        # One bid on the site -> levels 2-4 must be cleared, not left stale.
        quotes = TSETMCCollector().parse(SAMPLE_TSETMC_RAW)
        by_symbol = {q.source_symbol: q for q in quotes}
        assert by_symbol["TSETMC_FREE_DEMAND_L1"].last_price == 50000.0
        for level in (2, 3, 4):
            empty = by_symbol[f"TSETMC_FREE_DEMAND_L{level}"]
            assert empty.last_price is None and empty.raw == {"empty": True}

    def test_parses_demand_and_supply_price_levels(self):
        collector = TSETMCCollector()
        quotes = collector.parse(SAMPLE_TSETMC_RAW)
        by_symbol = {q.source_symbol: q for q in quotes}

        demand_l1 = by_symbol["TSETMC_FREE_DEMAND_L1"]
        assert demand_l1.last_price == 50000.0  # from pMeDem, not pMeOf
        assert demand_l1.volume == 2000.0
        assert demand_l1.transaction_count == 1

        supply_l1 = by_symbol["TSETMC_FREE_SUPPLY_L1"]
        assert supply_l1.last_price == 50000.0  # from pMeOf
        assert supply_l1.volume == 12450.0
        assert supply_l1.transaction_count == 4

        supply_l2 = by_symbol["TSETMC_FREE_SUPPLY_L2"]
        assert supply_l2.value == 63000000000.0

    def test_parses_per_contract_current_price(self):
        collector = TSETMCCollector()
        quotes = collector.parse(SAMPLE_TSETMC_RAW)
        contract = next(q for q in quotes if q.source_symbol == "DDP00PFBEXW050621")
        assert contract.last_price == 59000.0
        assert contract.transaction_count == 2

    def test_daily_history_lands_under_the_same_symbol_as_the_live_contract(self):
        collector = TSETMCCollector()
        quotes = collector.parse(SAMPLE_TSETMC_RAW)
        history_points = [
            q
            for q in quotes
            if q.source_symbol == "DDP00PFBEXW050621" and q.observed_at.day in (1, 2)
        ]
        assert len(history_points) == 2
        by_day = {q.observed_at.day: q for q in history_points}
        assert by_day[2].last_price == 59500.0
        assert by_day[1].last_price == 58596.0

    def _contract_quote(self, **info):
        raw = {**SAMPLE_TSETMC_RAW, "contracts": {"24591292296063193": {"closingPriceInfo": info}}, "daily_history": {}}
        return next(q for q in TSETMCCollector().parse(raw) if q.source_symbol == "DDP00PFBEXW050621")

    def test_contract_change_is_computed_against_yesterdays_price(self):
        # Live 2026-10-11 values: priceChange stays 0.0 mid-session.
        q = self._contract_quote(pClosing=67937.0, pDrCotVal=67000.0, priceChange=0.0, priceYesterday=45000.0, zTotTran=8.0)
        assert q.price_change == 22937.0
        assert q.price_change_percent == pytest.approx(50.97, abs=0.01)

    def test_placeholder_yesterday_price_gives_no_change_instead_of_a_huge_one(self):
        # First trading day: priceYesterday=1.0 would otherwise mean +8,524,300%.
        q = self._contract_quote(pClosing=85244.0, pDrCotVal=87610.0, priceChange=0.0, priceYesterday=1.0, zTotTran=81.0)
        assert q.last_price == 85244.0
        assert q.price_change is None and q.price_change_percent is None

    def test_placeholder_price_of_one_is_not_shown_as_a_price(self):
        q = self._contract_quote(pClosing=1.0, pDrCotVal=1.0, priceYesterday=1.0, zTotTran=0.0)
        assert q.last_price is None and q.close_price is None

    def test_daily_history_skips_days_without_trades(self):
        # Live rows for untraded days carry pClosing=1 (or yesterday's
        # price) - placeholders, not observations.
        no_trade_day = {
            "dEven": 20260830, "pClosing": 1.0, "pDrCotVal": 1.0, "priceChange": 0.0,
            "zTotTran": 0.0, "qTotTran5J": 0.0, "qTotCap": 0.0,
        }
        history = SAMPLE_DAILY_HISTORY["24591292296063193"]["closingPriceDaily"] + [no_trade_day]
        raw = {**SAMPLE_TSETMC_RAW, "daily_history": {"24591292296063193": {"closingPriceDaily": history}}}

        quotes = TSETMCCollector().parse(raw)

        history_days = {q.raw["dEven"] for q in quotes if q.raw and "dEven" in q.raw}
        assert history_days == {20260901, 20260902}

    def test_unparseable_numeric_field_becomes_none_not_crash(self):
        collector = TSETMCCollector()
        broken = {
            **SAMPLE_TSETMC_RAW,
            "overview": {"powerOverview": {**SAMPLE_OVERVIEW["powerOverview"], "dggPlus60_MarketActivityQTotCap": "not-a-number"}},
        }
        quotes = collector.parse(broken)
        overview = next(q for q in quotes if q.source_symbol == "TSETMC_FREE_POWER_OVERVIEW")
        assert overview.value is None

    def test_empty_payload_returns_empty_list(self):
        collector = TSETMCCollector()
        assert collector.parse({}) == []
        assert collector.parse([]) == []


# Shaped like real responses captured live on 2026-08-22 from
# https://webapi.iee.ir/api/Home/GetTradesSummary_Power and
# https://webapi.iee.ir/api/PowerFreeMarket/GetFreePowerMarketAtAGlance?Lang=fa
# (trimmed to the fields the collector reads) - see docs/DATA_SOURCES.md.
SAMPLE_IEE_TRADES_SUMMARY = {
    "results": [
        {"period": "Day", "market": "Power", "tradedValue": 595715.997738, "tradedVolume": 165023676.0, "avgPrice": 4500.0, "tradeNo": 112},
        {"period": "Day", "market": "Green", "tradedValue": 283174.35384, "tradedVolume": 4204536.0, "avgPrice": 67350.0, "tradeNo": 22},
        {"period": "Day", "market": "Free", "tradedValue": 3528000.0, "tradedVolume": 33600000.0, "avgPrice": 105000.0, "tradeNo": 27},
        {"period": "Week", "market": "Power", "tradedValue": 595715.997738, "tradedVolume": 165023676.0, "avgPrice": 0.0, "tradeNo": 0},
        {"period": "Month", "market": "Power", "tradedValue": 39631519.214987, "tradedVolume": 11356357863.0, "avgPrice": 3533.0, "tradeNo": 1732},
    ],
    "isSuccess": True,
}

SAMPLE_IEE_FREE_GLANCE = {
    "results": [
        {
            "marketState": "باز",
            "totalTradesValue": "3,528,000,000,000",
            "totalTradesVolume": 200000,
            "totalTradesCount": "27",
            "kiloWattHours": "33,600,000",
        }
    ],
    "isSuccess": True,
}

# Trimmed to 2 of the 448 contracts seen live on 2026-08-22 from
# https://webapi.iee.ir/api/PowerMarket/GetDerivativePowerMarketAtGlance?Lang=fa
SAMPLE_IEE_DERIVATIVE_GLANCE = {
    "results": [
        {
            "marketStatus": "بسته",
            "totalTradeNo": "111",
            "totalTradeValue": "594,241,797,738",
            "totalKiloWattHours": "164,696,076",
            "trades": [
                {
                    "id": 193954,
                    "contract": "بارپايه ماهانه 14050501",
                    "date": "2026/08/22",
                    "closingPrice": "3,533",
                    "minPrice": "3,450",
                    "maxPrice": "3,600",
                    "avgPrice": "3533",
                    "tradeValueNumber": 399919031520,
                    "tradeNoNumber": 27,
                    "tradeVolumeNumber": 152126,
                    "insCode": "46989496890754718",
                    "kiloWattHours": "113,181,744",
                },
                {
                    "id": 193858,
                    "contract": "بار متوسط ماهانه 14050501",
                    "date": "2026/08/22",
                    "closingPrice": "3,957",
                    "minPrice": "3,612",
                    "maxPrice": "3,979",
                    "avgPrice": "3957",
                    "tradeValueNumber": 105201049998,
                    "tradeNoNumber": 34,
                    "tradeVolumeNumber": 142940,
                    "insCode": "38627205019205095",
                    "kiloWattHours": "26,586,840",
                },
            ],
        }
    ],
    "isSuccess": True,
}


class TestIEENewCollectorParse:
    def test_parses_day_rows_from_trades_summary(self):
        collector = IEENewCollector()
        quotes = collector.parse({"trades_summary": SAMPLE_IEE_TRADES_SUMMARY, "free_glance": {}})

        symbols = {q.source_symbol for q in quotes}
        assert symbols == {"IEE_POWER_DAY", "IEE_GREEN_DAY", "IEE_FREE_DAY"}

        power = next(q for q in quotes if q.source_symbol == "IEE_POWER_DAY")
        assert power.last_price == 4500.0
        assert power.transaction_count == 112
        # tradedValue is millions of Rials at the source; value is Rials.
        assert power.value == pytest.approx(595715997738.0)
        assert power.raw["tradedValue"] == 595715.997738

    def test_ignores_non_day_periods(self):
        collector = IEENewCollector()
        quotes = collector.parse({"trades_summary": SAMPLE_IEE_TRADES_SUMMARY, "free_glance": {}})
        assert all("_DAY" in q.source_symbol for q in quotes)

    def test_parses_comma_formatted_free_glance_numbers(self):
        collector = IEENewCollector()
        quotes = collector.parse({"trades_summary": {}, "free_glance": SAMPLE_IEE_FREE_GLANCE})

        assert len(quotes) == 1
        live = quotes[0]
        assert live.source_symbol == "IEE_FREE_LIVE"
        assert live.value == 3528000000000.0
        assert live.transaction_count == 27
        assert live.volume == 200000.0
        assert live.raw["marketState"] == "باز"

    def test_malformed_comma_number_becomes_none_not_crash(self):
        collector = IEENewCollector()
        broken = {
            "results": [{**SAMPLE_IEE_FREE_GLANCE["results"][0], "totalTradesValue": "not-a-number"}],
            "isSuccess": True,
        }
        quotes = collector.parse({"trades_summary": {}, "free_glance": broken})
        assert len(quotes) == 1
        assert quotes[0].value is None

    def test_empty_payload_returns_empty_list(self):
        collector = IEENewCollector()
        assert collector.parse({}) == []
        assert collector.parse("not a dict") == []

    def test_parses_per_contract_trades_from_derivative_glance(self):
        collector = IEENewCollector()
        quotes = collector.parse({"trades_summary": {}, "free_glance": {}, "derivative_glance": SAMPLE_IEE_DERIVATIVE_GLANCE})

        symbols = {q.source_symbol for q in quotes}
        assert symbols == {
            "IEE_POWER_DERIVATIVE_TOTAL",
            "IEE_POWER_CONTRACT_46989496890754718",
            "IEE_POWER_CONTRACT_38627205019205095",
        }

        contract = next(q for q in quotes if q.source_symbol == "IEE_POWER_CONTRACT_46989496890754718")
        assert contract.last_price == 3533.0  # from comma-formatted "closingPrice"
        assert contract.value == 399919031520.0  # from pre-parsed "tradeValueNumber", not a comma string
        assert contract.transaction_count == 27
        assert contract.volume == 152126.0

        total = next(q for q in quotes if q.source_symbol == "IEE_POWER_DERIVATIVE_TOTAL")
        assert total.value == 594241797738.0
        assert total.transaction_count == 111

    def test_derivative_glance_persian_text_round_trips_correctly(self):
        # Regression check: an earlier investigation pass mistook this endpoint's
        # Persian text for corrupted encoding, when the real cause was a Windows
        # terminal mangling print() output during manual debugging (see
        # iee_new_collector.py module docstring). The parsed data itself was
        # always correct - assert that explicitly so this doesn't get "fixed"
        # again based on how it looks in a console.
        collector = IEENewCollector()
        quotes = collector.parse({"trades_summary": {}, "free_glance": {}, "derivative_glance": SAMPLE_IEE_DERIVATIVE_GLANCE})
        contract = next(q for q in quotes if q.source_symbol == "IEE_POWER_CONTRACT_46989496890754718")
        assert contract.raw["contract"] == "بارپايه ماهانه 14050501"

    def test_contract_with_missing_ins_code_is_skipped(self):
        collector = IEENewCollector()
        broken = {
            "results": [
                {
                    "marketStatus": "بسته",
                    "totalTradeNo": "0",
                    "totalTradeValue": "0",
                    "trades": [{**SAMPLE_IEE_DERIVATIVE_GLANCE["results"][0]["trades"][0], "insCode": None}],
                }
            ],
            "isSuccess": True,
        }
        quotes = collector.parse({"trades_summary": {}, "free_glance": {}, "derivative_glance": broken})
        assert all(not q.source_symbol.startswith("IEE_POWER_CONTRACT_") for q in quotes)


class TestIEEOldCollectorIsUnconfiguredStub:
    @pytest.mark.asyncio
    async def test_not_configured_cycle_makes_no_network_call(self):
        collector = IEEOldCollector()
        assert collector.configured is False

        async with httpx.AsyncClient() as client:
            result = await collector.run_cycle(client)

        assert result.status == "not_configured"
        assert result.quotes == []


class TestNormalizedQuoteValidity:
    def test_negative_price_is_invalid(self):
        q = NormalizedQuote(source_id="x", source_symbol="a", observed_at=datetime.now(timezone.utc), last_price=-1)
        assert not q.is_valid()

    def test_far_future_timestamp_is_invalid(self):
        q = NormalizedQuote(
            source_id="x",
            source_symbol="a",
            observed_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        assert not q.is_valid()

    def test_normal_quote_is_valid(self):
        q = NormalizedQuote(
            source_id="x", source_symbol="a", observed_at=datetime.now(timezone.utc), last_price=100, volume=10
        )
        assert q.is_valid()



class _FlakyCollector(BaseCollector):
    """Test double: fails a configurable number of times, then succeeds."""

    source_id = "flaky"
    name = "Flaky Test Collector"
    base_url = "http://example.invalid"
    configured = True

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self._fail_times = fail_times
        self._calls = 0

    async def fetch_raw(self, client: httpx.AsyncClient):
        self._calls += 1
        if self._calls <= self._fail_times:
            raise httpx.ConnectError("simulated connection failure")
        return {"ok": [{"insCode": "X", "pDrCotVal": "1"}]}

    def parse(self, raw):
        return [
            NormalizedQuote(
                source_id=self.source_id,
                source_symbol=item["insCode"],
                observed_at=datetime.now(timezone.utc),
                last_price=float(item["pDrCotVal"]),
            )
            for item in raw.get("ok", [])
        ]


class TestCircuitBreakerAndBackoff:
    @pytest.mark.asyncio
    async def test_repeated_failures_open_the_circuit(self):
        from app.core.config import get_settings

        settings = get_settings()
        collector = _FlakyCollector(fail_times=999)

        async with httpx.AsyncClient() as client:
            for _ in range(settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
                result = await collector.run_cycle(client)
                assert result.status == "error"

        assert collector.state.status == "down"
        assert collector._circuit_is_open()

        # While open, run_cycle must short-circuit without calling fetch_raw again.
        calls_before = collector._calls
        async with httpx.AsyncClient() as client:
            result = await collector.run_cycle(client)
        assert result.status == "skipped"
        assert collector._calls == calls_before

    @pytest.mark.asyncio
    async def test_recovers_after_transient_failures_within_retry_budget(self):
        from app.core.config import get_settings

        settings = get_settings()
        assert settings.MAX_RETRIES >= 2
        collector = _FlakyCollector(fail_times=settings.MAX_RETRIES - 1)

        async with httpx.AsyncClient() as client:
            result = await collector.run_cycle(client)

        assert result.status == "success"
        assert collector.state.status == "healthy"
        assert collector.state.consecutive_failures == 0


def test_iee_poll_interval_never_drops_below_its_floor():
    # IEE's WAF throttles 5s polling with 403s - its floor must hold even
    # in the active session, while TSETMC keeps the normal interval.
    from app.collectors.manager import CollectorManager
    from app.core.config import get_settings

    settings = get_settings()
    manager = CollectorManager()
    by_id = {c.source_id: c for c in manager.collectors}
    assert manager._effective_interval(by_id["iee_new"]) >= settings.IEE_MIN_POLL_INTERVAL
    assert by_id["tsetmc"].min_poll_interval == 0.0


class TestQuoteFingerprint:
    def test_ignores_observation_time(self):
        now = datetime.now(timezone.utc)
        q1 = NormalizedQuote(source_id="s", source_symbol="a", observed_at=now, last_price=1)
        q2 = NormalizedQuote(source_id="s", source_symbol="a", observed_at=now + timedelta(seconds=5), last_price=1)
        assert quote_fingerprint(q1) == quote_fingerprint(q2)

    def test_changed_price_changes_fingerprint(self):
        now = datetime.now(timezone.utc)
        q1 = NormalizedQuote(source_id="s", source_symbol="a", observed_at=now, last_price=1)
        q2 = NormalizedQuote(source_id="s", source_symbol="a", observed_at=now, last_price=2)
        assert quote_fingerprint(q1) != quote_fingerprint(q2)

    def test_raw_only_change_changes_fingerprint(self):
        # e.g. the market flipping from open to closed with totals unchanged.
        now = datetime.now(timezone.utc)
        q1 = NormalizedQuote(source_id="s", source_symbol="a", observed_at=now, value=1, raw={"marketStateTitle": "باز"})
        q2 = NormalizedQuote(source_id="s", source_symbol="a", observed_at=now, value=1, raw={"marketStateTitle": "بسته"})
        assert quote_fingerprint(q1) != quote_fingerprint(q2)


@pytest.mark.asyncio
async def test_tsetmc_collector_fetch_raw_uses_mocked_http(respx_mock):
    from app.collectors.tsetmc_collector import BASE_LOAD_TYPE, BEST_LIMITS_TOP, FREE_POWER_FLOW_ID

    collector = TSETMCCollector()
    base = collector.base_url
    respx_mock.get(f"{base}/Energy/GetPowerOverview/{FREE_POWER_FLOW_ID}").mock(
        return_value=httpx.Response(200, json=SAMPLE_OVERVIEW)
    )
    respx_mock.get(f"{base}/BestLimits/GetBestLimitsTopPower/EnergyPowerBuy/{FREE_POWER_FLOW_ID}/{BEST_LIMITS_TOP}/{BASE_LOAD_TYPE}").mock(
        return_value=httpx.Response(200, json=SAMPLE_DEMAND)
    )
    respx_mock.get(f"{base}/BestLimits/GetBestLimitsTopPower/EnergyPowerSell/{FREE_POWER_FLOW_ID}/{BEST_LIMITS_TOP}/{BASE_LOAD_TYPE}").mock(
        return_value=httpx.Response(200, json=SAMPLE_SUPPLY)
    )
    all_ins_codes = ["24591292296063193", "25228469814401417", "12294662990767012"]
    for ins_code in all_ins_codes:
        respx_mock.get(f"{base}/ClosingPrice/GetClosingPriceInfo/{ins_code}").mock(
            return_value=httpx.Response(200, json=SAMPLE_CONTRACTS.get(ins_code, {"closingPriceInfo": {}}))
        )
        respx_mock.get(f"{base}/ClosingPrice/GetClosingPriceDailyList/{ins_code}/2000").mock(
            return_value=httpx.Response(200, json=SAMPLE_DAILY_HISTORY.get(ins_code, {"closingPriceDaily": []}))
        )

    async with httpx.AsyncClient() as client:
        raw = await collector.fetch_raw(client)

        assert raw["overview"] == SAMPLE_OVERVIEW
        assert raw["demand"] == SAMPLE_DEMAND
        assert raw["supply"] == SAMPLE_SUPPLY
        assert set(raw["contracts"].keys()) == set(all_ins_codes)
        assert set(raw["daily_history"].keys()) == set(all_ins_codes)  # first time seeing them - fetched

        # Second cycle: same contracts, already known - must NOT refetch daily history.
        raw2 = await collector.fetch_raw(client)
        assert raw2["daily_history"] == {}


@pytest.mark.asyncio
async def test_iee_new_collector_fetch_raw_uses_mocked_http(respx_mock):
    from app.collectors.iee_new_collector import _DERIVATIVE_GLANCE_PATH, _FREE_GLANCE_PATH, _TRADES_SUMMARY_PATH

    collector = IEENewCollector()
    respx_mock.get(f"{collector.base_url}{_TRADES_SUMMARY_PATH}").mock(
        return_value=httpx.Response(200, json=SAMPLE_IEE_TRADES_SUMMARY)
    )
    respx_mock.get(f"{collector.base_url}{_FREE_GLANCE_PATH}").mock(
        return_value=httpx.Response(200, json=SAMPLE_IEE_FREE_GLANCE)
    )
    respx_mock.get(f"{collector.base_url}{_DERIVATIVE_GLANCE_PATH}").mock(
        return_value=httpx.Response(200, json=SAMPLE_IEE_DERIVATIVE_GLANCE)
    )
    async with httpx.AsyncClient() as client:
        raw = await collector.fetch_raw(client)
    assert raw == {
        "trades_summary": SAMPLE_IEE_TRADES_SUMMARY,
        "free_glance": SAMPLE_IEE_FREE_GLANCE,
        "derivative_glance": SAMPLE_IEE_DERIVATIVE_GLANCE,
    }
