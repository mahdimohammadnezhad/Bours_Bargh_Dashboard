"""Historical patterns in the daily base-load price (brief sections 13 and 17).

Everything here is computed from the stored series; nothing is a model
output except the analogue similarity score (a distance, labelled as such).

* Seasonality: each trading day's log price minus the mean log price of its
  Jalali year, averaged per Jalali month. Using the Jalali year as the unit
  removes most of the strong nominal inflation and lines up with the
  regulated caps resetting at Nowruz. Only complete years count.
* Month-to-month transitions: the change between consecutive months'
  average prices, per year - "from Mehr to Aban the price fell in 5 of 6
  years". Includes inflation (it is what actually happened).
* Weekday: average change from the previous trading day, by weekday.
* Temperature: the same seasonal deviation binned by 7-day mean national
  temperature, plus their correlation.
* Analogues: past days whose conditions (recent momentum, volatility,
  price level vs its trailing year, temperature and its trend, time of
  year) were closest to today's, and what the price did over the next
  1/5/20 trading days. Historical evidence, not a prediction.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

import jdatetime

from app.analytics.forecast import jalali_day_fraction, jalali_month_of, monthly_prices, trailing_mean_temperature

MIN_YEAR_TRADING_DAYS = 100
WEEKDAY_LOOKBACK_YEARS = 3
TEMP_BINS = [(-50.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0), (20.0, 25.0), (25.0, 30.0), (30.0, 60.0)]
ANALOGUE_COUNT = 10
ANALOGUE_MIN_SEPARATION = 10  # trading days between chosen analogues
ANALOGUE_OUTCOMES = (1, 5, 20)
LEVEL_WINDOW = 250
MOMENTUM_WINDOW = 20


def _pct(log_change: float) -> float:
    return 100 * (math.exp(log_change) - 1)


@dataclass
class MonthPattern:
    month: int
    mean_deviation_pct: float
    std_pct: float
    years: int
    trading_days: int
    consistency: float  # share of years whose deviation has the same sign as the mean


@dataclass
class MonthTransition:
    from_month: int
    to_month: int
    mean_change_pct: float
    median_change_pct: float
    share_up: float
    years: int


@dataclass
class WeekdayPattern:
    weekday: int  # Python weekday (Mon=0); trading days are Sat-Wed
    mean_change_pct: float
    share_up: float
    n: int


@dataclass
class TemperatureBin:
    low: float
    high: float
    mean_deviation_pct: float
    n: int


@dataclass
class Analogue:
    day: date
    similarity: float
    price: float
    features: dict[str, float]
    outcomes_pct: dict[str, float]


@dataclass
class PatternsResult:
    status: str
    reason: str | None = None
    seasonal: list[MonthPattern] = field(default_factory=list)
    seasonal_years: list[int] = field(default_factory=list)
    transitions: list[MonthTransition] = field(default_factory=list)
    weekday: list[WeekdayPattern] = field(default_factory=list)
    weekday_since: date | None = None
    temperature_bins: list[TemperatureBin] = field(default_factory=list)
    temperature_correlation: float | None = None
    temperature_points: int = 0
    current_features: dict[str, float] = field(default_factory=dict)
    current_day: date | None = None
    analogues: list[Analogue] = field(default_factory=list)
    analogue_summary: dict[str, float | int | None] = field(default_factory=dict)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 10:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def seasonal_deviations(
    prices: list[tuple[date, float]], current_jalali_year: int, min_year_days: int = MIN_YEAR_TRADING_DAYS
) -> tuple[dict[date, float], list[int]]:
    """Per trading day: log price minus its (complete) Jalali year's mean."""
    by_year: dict[int, list[tuple[date, float]]] = {}
    for d, p in prices:
        by_year.setdefault(jalali_month_of(d)[0], []).append((d, math.log(p)))
    out: dict[date, float] = {}
    years: list[int] = []
    for year, rows in sorted(by_year.items()):
        if year >= current_jalali_year or len(rows) < min_year_days:
            continue
        mean = statistics.fmean(lp for _, lp in rows)
        out.update({d: lp - mean for d, lp in rows})
        years.append(year)
    return out, years


def seasonal_profile(deviations: dict[date, float]) -> list[MonthPattern]:
    per_year_month: dict[tuple[int, int], list[float]] = {}
    for d, dev in deviations.items():
        per_year_month.setdefault(jalali_month_of(d), []).append(dev)
    by_month: dict[int, list[tuple[float, int]]] = {}
    for (_, month), devs in per_year_month.items():
        by_month.setdefault(month, []).append((statistics.fmean(devs), len(devs)))
    out: list[MonthPattern] = []
    for month in range(1, 13):
        rows = by_month.get(month)
        if not rows:
            continue
        means = [m for m, _ in rows]
        mean = statistics.fmean(means)
        same_sign = sum(1 for m in means if (m > 0) == (mean > 0)) / len(means)
        out.append(
            MonthPattern(
                month=month,
                mean_deviation_pct=_pct(mean),
                std_pct=100 * statistics.pstdev(means) if len(means) > 1 else 0.0,
                years=len(means),
                trading_days=sum(n for _, n in rows),
                consistency=same_sign,
            )
        )
    return out


def month_transitions(daily: list[tuple[date, float, float, float]]) -> list[MonthTransition]:
    month_price = monthly_prices(daily)
    changes: dict[int, list[float]] = {}
    for (year, month), (price, _) in month_price.items():
        nxt = (year + 1, 1) if month == 12 else (year, month + 1)
        if nxt in month_price:
            changes.setdefault(month, []).append(math.log(month_price[nxt][0]) - math.log(price))
    out: list[MonthTransition] = []
    for month in range(1, 13):
        values = changes.get(month)
        if not values or len(values) < 2:
            continue
        out.append(
            MonthTransition(
                from_month=month,
                to_month=1 if month == 12 else month + 1,
                mean_change_pct=_pct(statistics.fmean(values)),
                median_change_pct=_pct(statistics.median(values)),
                share_up=sum(1 for v in values if v > 0) / len(values),
                years=len(values),
            )
        )
    return out


def weekday_profile(prices: list[tuple[date, float]], since: date) -> list[WeekdayPattern]:
    by_weekday: dict[int, list[float]] = {}
    for (d0, p0), (d1, p1) in zip(prices, prices[1:]):
        if d1 < since or (d1 - d0).days > 4:  # skip holiday gaps
            continue
        by_weekday.setdefault(d1.weekday(), []).append(math.log(p1) - math.log(p0))
    order = [5, 6, 0, 1, 2, 3, 4]  # Sat first
    return [
        WeekdayPattern(
            weekday=wd,
            mean_change_pct=_pct(statistics.fmean(v)),
            share_up=sum(1 for x in v if x > 0) / len(v),
            n=len(v),
        )
        for wd in order
        if (v := by_weekday.get(wd)) and len(v) >= 10
    ]


def temperature_relationship(
    deviations: dict[date, float], temps: dict[date, float]
) -> tuple[list[TemperatureBin], float | None, int]:
    pairs = [(t7, dev) for d, dev in deviations.items() if (t7 := trailing_mean_temperature(temps, d)) is not None]
    bins: list[TemperatureBin] = []
    for lo, hi in TEMP_BINS:
        devs = [dev for t, dev in pairs if lo <= t < hi]
        if len(devs) >= 10:
            bins.append(TemperatureBin(low=lo, high=hi, mean_deviation_pct=_pct(statistics.fmean(devs)), n=len(devs)))
    corr = _pearson([t for t, _ in pairs], [dev for _, dev in pairs])
    return bins, corr, len(pairs)


def _features(i: int, days: list[date], logp: list[float], temps: dict[date, float]) -> dict[str, float] | None:
    if i < max(MOMENTUM_WINDOW, 60):
        return None
    t7 = trailing_mean_temperature(temps, days[i])
    t7_prev = trailing_mean_temperature(temps, days[i] - timedelta(days=14))
    if t7 is None or t7_prev is None:
        return None
    returns = [logp[k] - logp[k - 1] for k in range(i - MOMENTUM_WINDOW + 1, i + 1)]
    window = logp[max(0, i - LEVEL_WINDOW + 1) : i + 1]
    fraction, _ = jalali_day_fraction(days[i])
    return {
        "momentum_20d": logp[i] - logp[i - MOMENTUM_WINDOW],
        "volatility_20d": statistics.pstdev(returns),
        "level_vs_year": logp[i] - statistics.fmean(window),
        "temperature_7d": t7,
        "temperature_change_14d": t7 - t7_prev,
        "season_sin": math.sin(2 * math.pi * fraction),
        "season_cos": math.cos(2 * math.pi * fraction),
    }


# Season is two coordinates of one quantity, so each counts half.
_FEATURE_WEIGHTS = {
    "momentum_20d": 1.0,
    "volatility_20d": 1.0,
    "level_vs_year": 1.0,
    "temperature_7d": 1.0,
    "temperature_change_14d": 1.0,
    "season_sin": 0.5,
    "season_cos": 0.5,
}


def find_analogues(
    prices: list[tuple[date, float]], temps: dict[date, float]
) -> tuple[dict[str, float], list[Analogue], dict[str, float | int | None]]:
    days = [d for d, _ in prices]
    logp = [math.log(p) for _, p in prices]
    current = _features(len(days) - 1, days, logp, temps)
    if current is None:
        return {}, [], {}
    horizon = max(ANALOGUE_OUTCOMES)
    candidates = {i: f for i in range(len(days) - horizon) if (f := _features(i, days, logp, temps)) is not None}
    if len(candidates) < 50:
        return current, [], {}

    keys = list(_FEATURE_WEIGHTS)
    stats = {}
    for k in keys:
        values = [f[k] for f in candidates.values()] + [current[k]]
        stats[k] = (statistics.fmean(values), statistics.pstdev(values) or 1.0)

    def distance(f: dict[str, float]) -> float:
        return math.sqrt(sum(_FEATURE_WEIGHTS[k] * ((f[k] - current[k]) / stats[k][1]) ** 2 for k in keys))

    dims = sum(_FEATURE_WEIGHTS.values())
    ranked = sorted(candidates.items(), key=lambda item: distance(item[1]))
    chosen: list[int] = []
    for i, _ in ranked:
        if all(abs(i - j) >= ANALOGUE_MIN_SEPARATION for j in chosen):
            chosen.append(i)
        if len(chosen) == ANALOGUE_COUNT:
            break

    analogues = []
    for i in chosen:
        d = distance(candidates[i])
        analogues.append(
            Analogue(
                day=days[i],
                similarity=100 * math.exp(-(d * d) / (2 * dims)),
                price=math.exp(logp[i]),
                features=_display_features(candidates[i]),
                outcomes_pct={f"{h}d": _pct(logp[i + h] - logp[i]) for h in ANALOGUE_OUTCOMES},
            )
        )

    def outcome(h: int) -> list[float]:
        return [a.outcomes_pct[f"{h}d"] for a in analogues]

    summary: dict[str, float | int | None] = {"n": len(analogues)}
    for h in ANALOGUE_OUTCOMES:
        values = outcome(h)
        summary[f"share_up_{h}d"] = sum(1 for v in values if v > 0) / len(values) if values else None
        summary[f"median_{h}d_pct"] = statistics.median(values) if values else None
    summary["mean_similarity"] = statistics.fmean(a.similarity for a in analogues) if analogues else None
    return _display_features(current), analogues, summary


def _display_features(f: dict[str, float]) -> dict[str, float]:
    """Percentages / degrees for display; season coordinates are dropped."""
    return {
        "momentum_20d_pct": _pct(f["momentum_20d"]),
        "volatility_20d_pct": 100 * f["volatility_20d"],
        "level_vs_year_pct": _pct(f["level_vs_year"]),
        "temperature_7d": f["temperature_7d"],
        "temperature_change_14d": f["temperature_change_14d"],
    }


def build_patterns(
    daily: list[tuple[date, float, float, float]],
    temps: dict[date, float],
    today: date,
    min_days: int = 250,
    min_year_days: int = MIN_YEAR_TRADING_DAYS,
) -> PatternsResult:
    """min_days / min_year_days are lower for young markets (Free Power)."""
    prices = sorted((d, p) for d, p, _, _ in daily if p and p > 0)
    if len(prices) < min_days:
        return PatternsResult(status="insufficient_data", reason="price_history")
    current_year = jdatetime.date.fromgregorian(date=today).year
    deviations, years = seasonal_deviations(prices, current_year, min_year_days)
    since = date(today.year - WEEKDAY_LOOKBACK_YEARS, today.month, min(today.day, 28))
    bins, corr, n_temp = temperature_relationship(deviations, temps)
    current, analogues, summary = find_analogues(prices, temps)
    return PatternsResult(
        status="ok",
        seasonal=seasonal_profile(deviations),
        seasonal_years=years,
        transitions=month_transitions(daily),
        weekday=weekday_profile(prices, since),
        weekday_since=since,
        temperature_bins=bins,
        temperature_correlation=corr,
        temperature_points=n_temp,
        current_features=current,
        current_day=prices[-1][0],
        analogues=analogues,
        analogue_summary=summary,
    )
