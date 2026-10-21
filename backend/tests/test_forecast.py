import math
import random
from datetime import date, timedelta

import pytest

from app.analytics.forecast import (
    ModelScore,
    TRADING_WEEKDAYS,
    _solve,
    build_daily_forecast,
    build_monthly_outlook,
    jalali_month_days,
    monthly_prices,
    select_model,
)
from app.analytics.patterns import build_patterns
from app.analytics.recommendation import build_recommendation
from app.services.historical_ingestion import (
    DAILY_SERIES,
    POWER_BASELOAD_SYMBOL,
    aggregate_daily_vwap,
    aggregate_power_baseload_daily,
)
from app.services.weather import CITIES, combine_locations


def synthetic_market(years: int = 6, seed: int = 7, noise: float = 0.01):
    """A market whose price really is driven by temperature, season,
    inflation and a Nowruz reset - so the tests can check the engine finds
    it, rather than only that it runs. Returns (daily rows, temps, today)."""
    rng = random.Random(seed)
    start = date(2019, 3, 21)  # 1398/01/01
    today = start + timedelta(days=365 * years + 200)
    temps: dict[date, float] = {}
    rows = []
    d = start - timedelta(days=30)
    while d <= today + timedelta(days=16):
        phase = 2 * math.pi * ((d - start).days % 365.25) / 365.25
        temps[d] = 17 + 13 * math.sin(phase - 1.2) + rng.gauss(0, 1.5)
        d += timedelta(days=1)
    d = start
    while d <= today:
        if d.weekday() in TRADING_WEEKDAYS:
            t7 = sum(temps[d - timedelta(days=i)] for i in range(7)) / 7
            years_elapsed = (d - start).days / 365.25
            log_price = 6.0 + 0.30 * int(years_elapsed) + 0.02 * max(t7 - 18, 0) + rng.gauss(0, noise)
            price = math.exp(log_price)
            kwh = 1e8
            rows.append((d, price, price * kwh, kwh))
        d += timedelta(days=1)
    return rows, temps, today


class TestLinearAlgebra:
    def test_solves_a_small_system(self):
        assert _solve([[2.0, 1.0], [1.0, 3.0]], [3.0, 5.0]) == pytest.approx([0.8, 1.4])

    def test_singular_system_returns_none(self):
        assert _solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0]) is None


class TestModelSelection:
    def _score(self, model: str, mape: float) -> ModelScore:
        return ModelScore(model=model, n=100, mae=1.0, mape=mape, directional_accuracy=None)

    def test_default_is_strictly_the_lowest_error(self):
        # Real monthly case (2026-10-11): season_only 12.47% vs temp_season 12.64%.
        assert select_model([self._score("temp_season", 12.64), self._score("season_only", 12.47)]) == "season_only"
        # Real daily case: "no change" beats the regression variants.
        assert select_model([self._score("temp_season", 6.34), self._score("naive", 5.85)]) == "naive"


class TestMonthlyOutlook:
    def test_beats_naive_and_finds_the_temperature_effect(self):
        rows, temps, today = synthetic_market()
        forecast_days = {d for d in temps if d > today}
        outlook = build_monthly_outlook(rows, temps, forecast_days, today)

        assert outlook.status == "ok"
        by_model = {s.model: s for s in outlook.scores}
        assert by_model[outlook.selected_model].mape < by_model["naive"].mape
        assert len(outlook.points) == 6
        assert all(p.low <= p.price <= p.high for p in outlook.points)
        assert outlook.coefficients["cdd"] > 0  # warmer -> pricier, as generated
        # Every month has a temperature, including the in-progress one -
        # otherwise the month axis of the temperature chart skips it.
        assert all(h.t_mean is not None for h in outlook.history)

    def test_every_validated_model_has_its_own_outlook_and_range(self):
        rows, temps, today = synthetic_market()
        outlook = build_monthly_outlook(rows, temps, {d for d in temps if d > today}, today)

        assert set(outlook.points_by_model) == {s.model for s in outlook.scores}
        assert outlook.points == outlook.points_by_model[outlook.selected_model]
        assert outlook.selected_model == min(outlook.scores, key=lambda s: s.mape).model
        for points in outlook.points_by_model.values():
            assert len(points) == 6
            assert all(p.low <= p.price <= p.high for p in points)
        # "No change" is flat by construction; the regression variants are not.
        naive = outlook.points_by_model["naive"]
        assert len({round(p.price, 6) for p in naive}) == 1

    def test_too_little_history_is_reported_not_guessed(self):
        rows, temps, today = synthetic_market(years=2)
        outlook = build_monthly_outlook(rows, temps, set(), today)
        assert outlook.status == "insufficient_data"
        assert outlook.points == []

    def test_jalali_month_days_cover_the_month(self):
        days = jalali_month_days((1405, 7))  # Mehr: 30 days
        assert len(days) == 30
        assert days[0] == date(2026, 9, 23)

    def test_monthly_price_is_volume_weighted(self):
        d1, d2, d3 = date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 27)
        rows = [(d1, 100.0, 100.0 * 1, 1.0), (d2, 200.0, 200.0 * 3, 3.0), (d3, 200.0, 200.0 * 1, 1.0)]
        price, n = monthly_prices(rows)[(1405, 7)]
        assert price == pytest.approx((100 + 600 + 200) / 5)
        assert n == 3


class TestDailyForecast:
    def test_validates_and_forecasts_only_trading_days_within_weather_coverage(self):
        rows, temps, today = synthetic_market()
        result = build_daily_forecast([(d, p) for d, p, _, _ in rows], temps)

        assert result.status == "ok"
        assert {s.model for s in result.scores} >= {"naive", "drift", "temp_season"}
        assert result.points
        assert all(p.day.weekday() in TRADING_WEEKDAYS for p in result.points)
        assert all(p.day <= max(temps) for p in result.points)
        assert all(p.low <= p.price <= p.high for p in result.points)
        assert set(result.points_by_model) == {s.model for s in result.scores}
        assert result.points == result.points_by_model[result.selected_model]


class TestPatternsAndRecommendation:
    def test_seasonal_profile_peaks_in_summer(self):
        rows, temps, today = synthetic_market(noise=0.002)
        patterns = build_patterns(rows, temps, today)
        assert patterns.status == "ok"
        by_month = {m.month: m.mean_deviation_pct for m in patterns.seasonal}
        # Generated with a cooling-load premium: Tir/Mordad above Dey/Bahman.
        assert by_month[5] > by_month[10]
        assert patterns.temperature_correlation is not None and patterns.temperature_correlation > 0.3

    def test_analogues_carry_outcomes_and_stay_apart(self):
        rows, temps, today = synthetic_market()
        patterns = build_patterns(rows, temps, today)
        assert 0 < len(patterns.analogues) <= 10
        assert all(set(a.outcomes_pct) == {"1d", "5d", "20d"} for a in patterns.analogues)
        assert patterns.analogue_summary["n"] == len(patterns.analogues)

    def test_recommendation_is_evidence_backed(self):
        rows, temps, today = synthetic_market()
        forecast_days = {d for d in temps if d > today}
        monthly = build_monthly_outlook(rows, temps, forecast_days, today)
        daily = build_daily_forecast([(d, p) for d, p, _, _ in rows], temps)
        patterns = build_patterns(rows, temps, today)
        rec = build_recommendation(monthly, daily, patterns, volatility_percentile=50.0)

        assert rec.status == "ok"
        assert rec.signal in {"upward_pressure", "downward_pressure", "mixed"}
        assert {e.key for e in rec.evidence} >= {"outlook_next_month", "seasonal_transition", "analogues_20d"}
        assert all(0.0 <= e.strength <= 1.0 for e in rec.evidence)
        if rec.signal != "mixed":
            assert rec.agreement_pct is not None and 0 <= rec.agreement_pct <= 100

    def test_naive_short_term_model_casts_no_vote(self):
        rows, temps, today = synthetic_market()
        monthly = build_monthly_outlook(rows, temps, set(), today)
        daily = build_daily_forecast([(d, p) for d, p, _, _ in rows], temps)
        daily.selected_model = "naive"
        rec = build_recommendation(monthly, daily, build_patterns(rows, temps, today), None)
        short = next(e for e in rec.evidence if e.key == "short_term")
        assert short.direction == 0 and short.strength == 0.0


class TestBaseloadAggregation:
    ROWS = [
        # Shaped like live GetDeriativePowerMarketStatistics rows (2026-10-11).
        {"contract": "بارپايه ماهانه 14050801", "date": "1405/07/18", "avgPrice": "3400", "tradeNo": "79",
         "tradeValue": "2,958,134,731,920", "tradeValueNumber": 2958134731920, "kiloWattHours": "869,950,080",
         "energySymbol": "DAP00PFBEXM050801"},
        {"contract": "بارپايه روزانه 14050727", "date": "1405/07/18", "avgPrice": "3466", "tradeNo": "20",
         "tradeValue": "84,837,480,000", "tradeValueNumber": 84837480000, "kiloWattHours": "24,480,000",
         "energySymbol": "DAP00PFBEXD050727"},
        {"contract": "بارپيك ماهانه 14050801", "date": "1405/07/18", "avgPrice": "4100", "tradeNo": "5",
         "tradeValue": "1,000,000,000", "kiloWattHours": "243,902", "energySymbol": "DAP00PFPEXM050801"},
        {"contract": "بارپايه هفتگي 14050802", "date": "1405/07/18", "avgPrice": "0", "tradeNo": "0",
         "tradeValue": "0", "kiloWattHours": "0", "energySymbol": "DAP00PFBEXW050802"},
    ]

    def test_one_vwap_quote_per_day_from_traded_base_load_only(self):
        quotes = aggregate_power_baseload_daily(self.ROWS)
        assert len(quotes) == 1
        q = quotes[0]
        assert q.source_symbol == POWER_BASELOAD_SYMBOL
        assert q.observed_at.date() == date(2026, 10, 10)
        expected = (2958134731920 + 84837480000) / (869950080 + 24480000)
        assert q.last_price == pytest.approx(expected, abs=0.01)
        assert q.transaction_count == 99
        assert len(q.raw["contracts"]) == 2  # peak and untraded rows left out

    def test_physical_free_power_excludes_self_supply_and_plain_power(self):
        # Live 2026-10-21: the physical Free-market report also lists
        # "برق خودتامین" (~11-18k) and "برق" auctions - not Free Power.
        rows = [
            {"tradeDateShamsi": "1405/07/29", "instrumentDisplayName": "برق آزاد", "energySymbol": "DDGNZCAB00W050809",
             "tradeNo": "3", "totalValueRials": "95,981,760,000", "kiloWattHours": "799,848", "tradedAveragePrice": "120,000"},
            {"tradeDateShamsi": "1405/07/29", "instrumentDisplayName": "برق خودتامین", "energySymbol": "DSECRCAB00M050201",
             "tradeNo": "1", "totalValueRials": "1,800,000,000", "kiloWattHours": "100,000", "tradedAveragePrice": "18,000"},
        ]
        quotes = aggregate_daily_vwap(rows, DAILY_SERIES["free_physical"])
        assert len(quotes) == 1
        assert quotes[0].last_price == pytest.approx(120000, abs=1)
        assert quotes[0].source_symbol == DAILY_SERIES["free_physical"].symbol

    def test_single_contract_vwap_equals_iee_avg_price(self):
        q = aggregate_power_baseload_daily(self.ROWS[:1])[0]
        assert q.last_price == pytest.approx(3400, abs=1)


class TestWeatherCombination:
    def _payload(self, values_per_city: list[list[float | None]]):
        return [
            {"daily": {"time": ["2026-10-10", "2026-10-11"], "temperature_2m_mean": v,
                       "temperature_2m_max": v, "temperature_2m_min": v}}
            for v in values_per_city
        ]

    def test_population_weighted_mean(self):
        values = [[float(i), float(i)] for i in range(len(CITIES))]
        days = combine_locations(self._payload(values))
        total = sum(c[3] for c in CITIES)
        expected = sum(i * c[3] for i, c in enumerate(CITIES)) / total
        assert days[0].t_mean == pytest.approx(expected, abs=0.01)
        assert days[0].per_city["Tehran"] == 0.0

    def test_day_with_too_few_cities_is_dropped(self):
        values = [[20.0, None] if i < 2 else [20.0, None] for i in range(len(CITIES))]
        values[0][1] = 25.0  # only one city reports the second day
        days = combine_locations(self._payload(values))
        assert [d.day for d in days] == [date(2026, 10, 10)]

    def test_wrong_location_count_is_an_error(self):
        with pytest.raises(ValueError):
            combine_locations(self._payload([[1.0, 1.0]]))
