"""Price forecasts driven by temperature and season (brief section 19).

Series: the power market's daily base-load VWAP (Rials/kWh). In every year
since 1399 it rises through spring, peaks in Tir-Mordad with the summer
cooling load, falls through autumn and winter, and jumps at Nowruz when the
year's regulated price caps reset - on top of strong nominal inflation.

Two horizons, because the data says the drivers matter at different scales
(walk-forward validation on the real series, 2026-10-11):

* Monthly outlook (main, next 6 Jalali months). The log change between two
  months' average prices is regressed on how the drivers change between
  them: months elapsed (inflation drift), Jalali month-of-year (2 Fourier
  harmonics), Nowruz crossings (cap resets) and cooling/heating degrees of
  the monthly mean national temperature. Future months' temperature is the
  16-day weather forecast where it reaches and the month's climatological
  normal elsewhere. Validated against "no change" and "drift": at 3 months
  ahead 12.9% vs 19.3% MAPE and 78% vs 45% direction hits; at 6 months
  15.8% vs 29.3%.

* Short term (next 14 days, daily). Same idea on day pairs with 7-day mean
  temperature. Over two weeks the seasonal move is a fraction of a percent
  against several percent of daily noise and the 1405 cap shock, and in
  validation "no change" was slightly *more* accurate (MAPE 5.9% vs 6.3%).
  So the short-term default is whichever model validates best - an honest
  range around the current price - and every model's numbers are reported.

For both horizons every validated model's forecast is produced
(`points_by_model`), each with an 80% range from its own validation errors.
The default (`selected_model`, used by the recommendation engine) is the
lowest validated MAPE; the UI lets the user switch to any other.

Both are anchored on the last observed price (the regression explains the
move, not the level), fitted by weighted ridge least squares with recent
data weighing more, stdlib only. Validation is walk-forward only: at each
origin, models see nothing after it - including temperature: the monthly
validation uses climatological normals for the target months, exactly as a
live forecast beyond the weather forecast does.
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

import jdatetime

CDD_BASE_C = 18.0
HDD_BASE_C = 18.0
RECENCY_TAU_DAYS = 3 * 365.0
RIDGE_ALPHA = 1e-3
INTERVAL_QUANTILES = (0.10, 0.90)  # 80% prediction interval
MIN_TRADING_DAYS = 250
TRADING_WEEKDAYS = {5, 6, 0, 1, 2}  # Sat..Wed in Python's Mon=0 numbering; IEE trades Sat-Wed

# --- daily (short term)
HORIZON_DAYS = 14
TEMP_WINDOW_DAYS = 7
DAILY_VALIDATION_YEARS = 2
DAILY_ORIGIN_STEP = 3
DAILY_BUCKETS = [(1, 3), (4, 7), (8, 14)]
DAILY_FEATURES = ["drift", "cdd", "hdd", "season_s1", "season_c1", "season_s2", "season_c2", "nowruz"]

# --- monthly (outlook)
HORIZON_MONTHS = 6
MONTH_MIN_TRADING_DAYS = 3
MONTH_MIN_TEMP_DAYS = 20
MONTHLY_MIN_TRAINING_MONTHS = 36
MONTHLY_FEATURES = ["drift", "season_s1", "season_c1", "season_s2", "season_c2", "nowruz", "cdd", "hdd"]

FEATURE_GROUP = {
    "drift": "drift",
    "cdd": "temperature",
    "hdd": "temperature",
    "season_s1": "season",
    "season_c1": "season",
    "season_s2": "season",
    "season_c2": "season",
    "nowruz": "nowruz",
}
SEASON_FEATURES = ["season_s1", "season_c1", "season_s2", "season_c2"]
TEMP_FEATURES = ["cdd", "hdd"]
# Regression variants share one accumulated design matrix and differ only in
# which columns they use.
REGRESSION_VARIANTS: dict[str, list[str]] = {
    "temp_season": ["drift", *TEMP_FEATURES, *SEASON_FEATURES, "nowruz"],
    "season_only": ["drift", *SEASON_FEATURES, "nowruz"],
    "temp_only": ["drift", *TEMP_FEATURES, "nowruz"],
}
BASELINES = ["naive", "drift"]


def select_model(scores: list[ModelScore]) -> str:
    """The default model: lowest validated MAPE. Every validated model's
    forecast is produced too, so the user can switch to any of them."""
    return min(scores, key=lambda s: s.mape).model


# ================================================================ shared


@dataclass
class ModelScore:
    model: str
    n: int
    mae: float
    mape: float
    directional_accuracy: float | None
    by_horizon: dict[str, dict[str, float | int | None]] = field(default_factory=dict)


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None if singular."""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(n):
            if r != col:
                factor = a[r][col] / a[col][col]
                if factor:
                    for c in range(col, n + 1):
                        a[r][c] -= factor * a[col][c]
    return [a[i][n] / a[i][i] for i in range(n)]


class _Accumulator:
    """Running weighted X'X and X'y, so walk-forward refits cost one pass."""

    def __init__(self, k: int) -> None:
        self.xtx = [[0.0] * k for _ in range(k)]
        self.xty = [0.0] * k
        self.count = 0

    def add(self, x: list[float], y: float, w: float) -> None:
        for i, xi in enumerate(x):
            if xi == 0.0:
                continue
            wxi = w * xi
            self.xty[i] += wxi * y
            row = self.xtx[i]
            for j, xj in enumerate(x):
                row[j] += wxi * xj
        self.count += 1

    def solve(self, columns: list[int]) -> list[float] | None:
        sub = [[self.xtx[i][j] for j in columns] for i in columns]
        for d, i in enumerate(columns):
            # Scale-aware ridge: shrink each column relative to its own size.
            sub[d][d] += RIDGE_ALPHA * self.xtx[i][i] + 1e-9
        return _solve(sub, [self.xty[i] for i in columns])


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    rank = q * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def _metrics(rows: list[tuple[float, float, float]]) -> dict[str, float | int | None]:
    """rows: (actual, predicted, origin_price)."""
    directional = [
        (p - o > 0) == (a - o > 0)
        for a, p, o in rows
        if abs(a - o) / o >= 0.0025 and abs(p - o) / o >= 0.0005
    ]
    return {
        "n": len(rows),
        "mae": statistics.fmean(abs(p - a) for a, p, _ in rows),
        "mape": 100 * statistics.fmean(abs(p - a) / a for a, p, _ in rows),
        # Undefined for a model that never predicts a move (naive).
        "directional_accuracy": 100 * statistics.fmean(directional) if len(directional) >= 10 else None,
    }


def _score(model: str, records: list[tuple[str, float, float, float]]) -> ModelScore:
    """records: (horizon_key, actual, predicted, origin_price)."""
    overall = _metrics([r[1:] for r in records])
    by_horizon: dict[str, dict[str, float | int | None]] = {}
    for key in dict.fromkeys(r[0] for r in records):
        by_horizon[key] = _metrics([r[1:] for r in records if r[0] == key])
    return ModelScore(
        model=model,
        n=int(overall["n"]),
        mae=float(overall["mae"]),
        mape=float(overall["mape"]),
        directional_accuracy=overall["directional_accuracy"],  # type: ignore[arg-type]
        by_horizon=by_horizon,
    )


def _season_terms(fraction_of_year: float) -> tuple[float, float, float, float]:
    w = 2 * math.pi * fraction_of_year
    return math.sin(w), math.cos(w), math.sin(2 * w), math.cos(2 * w)


def _degree_days(t: float) -> tuple[float, float]:
    return max(t - CDD_BASE_C, 0.0), max(HDD_BASE_C - t, 0.0)


def _contributions(features: list[str], coefficients: dict[str, float], x: list[float]) -> dict[str, float]:
    """Per driver group, in log points (sum = predicted log change)."""
    parts: dict[str, float] = {}
    for name, value in zip(features, x):
        if name in coefficients:
            group = FEATURE_GROUP[name]
            parts[group] = parts.get(group, 0.0) + coefficients[name] * value
    return parts


# ================================================================ daily


@dataclass(frozen=True)
class DayDrivers:
    cdd: float
    hdd: float
    t7: float
    season: tuple[float, float, float, float]
    jalali_year: int


@dataclass
class DailyPoint:
    day: date
    price: float
    low: float
    high: float
    horizon_days: int
    t7: float | None
    contributions_pct: dict[str, float]


@dataclass
class DailyForecast:
    status: str
    reason: str | None = None
    last_day: date | None = None
    last_price: float | None = None
    points: list[DailyPoint] = field(default_factory=list)  # the selected model's
    points_by_model: dict[str, list[DailyPoint]] = field(default_factory=dict)
    scores: list[ModelScore] = field(default_factory=list)
    selected_model: str | None = None
    validation_origins: int = 0
    validation_start: date | None = None
    validation_end: date | None = None
    trading_days: int = 0


def trailing_mean_temperature(temps: dict[date, float], day: date, window: int = TEMP_WINDOW_DAYS) -> float | None:
    values = [temps[d] for i in range(window) if (d := day - timedelta(days=i)) in temps]
    return statistics.fmean(values) if len(values) >= window - 2 else None


def jalali_day_fraction(day: date) -> tuple[float, int]:
    j = jdatetime.date.fromgregorian(date=day)
    return (j - jdatetime.date(j.year, 1, 1)).days / 365.25, j.year


def day_drivers(temps: dict[date, float], day: date) -> DayDrivers | None:
    t7 = trailing_mean_temperature(temps, day)
    if t7 is None:
        return None
    fraction, jyear = jalali_day_fraction(day)
    cdd, hdd = _degree_days(t7)
    return DayDrivers(cdd=cdd, hdd=hdd, t7=t7, season=_season_terms(fraction), jalali_year=jyear)


def day_pair_features(d1: date, x1: DayDrivers, d2: date, x2: DayDrivers) -> list[float]:
    return [
        (d2 - d1).days / 30.0,
        x2.cdd - x1.cdd,
        x2.hdd - x1.hdd,
        *(b - a for a, b in zip(x1.season, x2.season)),
        1.0 if x2.jalali_year != x1.jalali_year else 0.0,
    ]


def _daily_bucket(h: int) -> str:
    for lo, hi in DAILY_BUCKETS:
        if lo <= h <= hi:
            return f"{lo}-{hi}"
    lo, hi = DAILY_BUCKETS[-1]
    return f"{lo}-{hi}"


def build_daily_forecast(
    prices: list[tuple[date, float]], temps: dict[date, float], horizon: int = HORIZON_DAYS
) -> DailyForecast:
    """prices: trading-day series. temps: national daily mean temperature,
    observed and forecast (forecast days bound how far ahead this goes)."""
    prices = sorted((d, p) for d, p in prices if p and p > 0)
    if len(prices) < MIN_TRADING_DAYS:
        return DailyForecast(status="insufficient_data", reason="price_history", trading_days=len(prices))
    days = [d for d, _ in prices]
    price_of = dict(prices)
    logp = {d: math.log(p) for d, p in prices}
    drivers = {d: x for d in days if (x := day_drivers(temps, d)) is not None}
    if len(drivers) < MIN_TRADING_DAYS:
        return DailyForecast(status="insufficient_data", reason="temperature_history", trading_days=len(prices))

    pairs: list[tuple[date, list[float], float]] = []
    for i, d1 in enumerate(days):
        if d1 not in drivers:
            continue
        for d2 in days[i + 1 :]:
            if (d2 - d1).days > horizon:
                break
            if d2 in drivers:
                pairs.append((d2, day_pair_features(d1, drivers[d1], d2, drivers[d2]), logp[d2] - logp[d1]))
    pairs.sort(key=lambda p: p[0])
    t_ref = days[-1]

    def weight(d2: date) -> float:
        return math.exp((d2 - t_ref).days / RECENCY_TAU_DAYS)

    columns = {name: [DAILY_FEATURES.index(f) for f in feats] for name, feats in REGRESSION_VARIANTS.items()}

    def predict(model: str, oi: int, d2: date, coefs: dict[str, list[float] | None]) -> float | None:
        origin = days[oi]
        p0 = price_of[origin]
        h = (d2 - origin).days
        if model == "naive":
            return p0
        if model == "drift":
            year_ago = days[bisect.bisect_left(days, origin - timedelta(days=365))]
            per_day = (logp[origin] - logp[year_ago]) / max((origin - year_ago).days, 1)
            return p0 * math.exp(per_day * h)
        beta = coefs.get(model)
        x2 = drivers.get(d2) or day_drivers(temps, d2)
        if beta is None or x2 is None or origin not in drivers:
            return None
        x = day_pair_features(origin, drivers[origin], d2, x2)
        return p0 * math.exp(sum(b * x[c] for b, c in zip(beta, columns[model])))

    # ---- walk-forward validation
    val_start = t_ref - timedelta(days=365 * DAILY_VALIDATION_YEARS)
    origin_idx = [i for i, d in enumerate(days) if d >= val_start and i < len(days) - 1][::DAILY_ORIGIN_STEP]
    acc = _Accumulator(len(DAILY_FEATURES))
    pointer = 0
    models = [*BASELINES, *REGRESSION_VARIANTS]
    records: dict[str, list[tuple[str, float, float, float]]] = {m: [] for m in models}
    residuals: dict[str, dict[str, list[float]]] = {m: {} for m in models}
    for oi in origin_idx:
        origin = days[oi]
        while pointer < len(pairs) and pairs[pointer][0] <= origin:
            d2, x, y = pairs[pointer]
            acc.add(x, y, weight(d2))
            pointer += 1
        if acc.count < 200 or origin not in drivers:
            continue
        coefs = {name: acc.solve(cols) for name, cols in columns.items()}
        for d2 in days[oi + 1 :]:
            h = (d2 - origin).days
            if h > horizon:
                break
            if d2 not in drivers:
                continue
            for model in models:
                pred = predict(model, oi, d2, coefs)
                if pred is None:
                    continue
                key = _daily_bucket(h)
                records[model].append((key, price_of[d2], pred, price_of[origin]))
                residuals[model].setdefault(key, []).append(logp[d2] - math.log(pred))

    scores = sorted((_score(m, r) for m, r in records.items() if len(r) >= 50), key=lambda s: s.mape)
    if not scores:
        return DailyForecast(status="insufficient_data", reason="validation", trading_days=len(prices))
    selected = select_model(scores)

    # ---- refit on everything; forecast with every validated model
    full = _Accumulator(len(DAILY_FEATURES))
    for d2, x, y in pairs:
        full.add(x, y, weight(d2))
    coefs = {name: full.solve(cols) for name, cols in columns.items()}
    last_i = len(days) - 1
    last_day, last_price = prices[-1]

    def forecast_with(model: str) -> list[DailyPoint]:
        out: list[DailyPoint] = []
        for i in range(1, horizon + 1):
            d2 = last_day + timedelta(days=i)
            if d2.weekday() not in TRADING_WEEKDAYS:
                continue
            x2 = day_drivers(temps, d2)
            if x2 is None:
                break  # beyond the weather forecast
            pred = predict(model, last_i, d2, coefs)
            if pred is None:
                break
            contributions: dict[str, float] = {}
            if model in REGRESSION_VARIANTS and last_day in drivers and coefs[model] is not None:
                x = day_pair_features(last_day, drivers[last_day], d2, x2)
                coef_map = dict(zip(REGRESSION_VARIANTS[model], coefs[model]))  # type: ignore[arg-type]
                contributions = {
                    k: 100 * (math.exp(v) - 1) for k, v in _contributions(DAILY_FEATURES, coef_map, x).items()
                }
            elif model == "drift":
                contributions = {"drift": 100 * (pred / last_price - 1)}
            resid = residuals[model].get(_daily_bucket(i)) or [0.0]
            out.append(
                DailyPoint(
                    day=d2,
                    price=pred,
                    low=pred * math.exp(_quantile(resid, INTERVAL_QUANTILES[0])),
                    high=pred * math.exp(_quantile(resid, INTERVAL_QUANTILES[1])),
                    horizon_days=i,
                    t7=x2.t7,
                    contributions_pct=contributions,
                )
            )
        return out

    points_by_model = {s.model: forecast_with(s.model) for s in scores}

    return DailyForecast(
        status="ok",
        last_day=last_day,
        last_price=last_price,
        points=points_by_model[selected],
        points_by_model=points_by_model,
        scores=scores,
        selected_model=selected,
        validation_origins=len(origin_idx),
        validation_start=days[origin_idx[0]] if origin_idx else None,
        validation_end=days[origin_idx[-1]] if origin_idx else None,
        trading_days=len(prices),
    )


# ================================================================ monthly

JMonth = tuple[int, int]  # (jalali_year, jalali_month)


@dataclass
class MonthHistory:
    month: JMonth
    price: float
    trading_days: int
    t_mean: float | None


@dataclass
class MonthPoint:
    month: JMonth
    horizon_months: int
    price: float
    low: float
    high: float
    t_mean: float
    t_source: str  # "forecast+normal" | "normal"
    t_normal: float
    contributions_pct: dict[str, float]


@dataclass
class MonthlyOutlook:
    status: str
    reason: str | None = None
    origin: JMonth | None = None
    origin_price: float | None = None
    origin_trading_days: int = 0
    origin_partial: bool = False
    history: list[MonthHistory] = field(default_factory=list)
    points: list[MonthPoint] = field(default_factory=list)  # the selected model's
    points_by_model: dict[str, list[MonthPoint]] = field(default_factory=dict)
    coefficients: dict[str, float] = field(default_factory=dict)
    scores: list[ModelScore] = field(default_factory=list)
    selected_model: str | None = None
    validation_origins: int = 0
    validation_start: JMonth | None = None
    validation_end: JMonth | None = None
    months_used: int = 0
    temperature_normals: dict[int, float] = field(default_factory=dict)


def _month_index(m: JMonth) -> int:
    return m[0] * 12 + m[1] - 1


def _from_index(i: int) -> JMonth:
    return i // 12, i % 12 + 1


def jalali_month_of(day: date) -> JMonth:
    j = jdatetime.date.fromgregorian(date=day)
    return j.year, j.month


def jalali_month_days(month: JMonth) -> list[date]:
    start = jdatetime.date(month[0], month[1], 1)
    nxt = _from_index(_month_index(month) + 1)
    end = jdatetime.date(nxt[0], nxt[1], 1)
    return [(start + timedelta(days=i)).togregorian() for i in range((end - start).days)]


def monthly_prices(daily: list[tuple[date, float, float, float]]) -> dict[JMonth, tuple[float, int]]:
    """daily rows: (day, price, value_rials, kwh) -> month: (VWAP, trading days)."""
    agg: dict[JMonth, list[float]] = {}
    for day, price, value, kwh in daily:
        bucket = agg.setdefault(jalali_month_of(day), [0.0, 0.0, 0])
        if value and kwh:
            bucket[0] += value
            bucket[1] += kwh
        else:  # no volume info: fall back to the price at unit weight
            bucket[0] += price
            bucket[1] += 1.0
        bucket[2] += 1
    return {m: (v / k, int(n)) for m, (v, k, n) in agg.items() if k > 0 and n >= MONTH_MIN_TRADING_DAYS}


def monthly_observed_temperature(temps: dict[date, float], forecast_days: set[date]) -> dict[JMonth, float]:
    obs: dict[JMonth, list[float]] = {}
    for d, t in temps.items():
        if d not in forecast_days:
            obs.setdefault(jalali_month_of(d), []).append(t)
    return {m: statistics.fmean(v) for m, v in obs.items() if len(v) >= MONTH_MIN_TEMP_DAYS}


def temperature_normals(month_temps: dict[JMonth, float], up_to: JMonth | None = None) -> dict[int, float]:
    by_moy: dict[int, list[float]] = {}
    for m, t in month_temps.items():
        if up_to is None or _month_index(m) <= _month_index(up_to):
            by_moy.setdefault(m[1], []).append(t)
    return {moy: statistics.fmean(v) for moy, v in by_moy.items()}


def _month_features(m0: JMonth, t0: float, m1: JMonth, t1: float) -> list[float]:
    s0 = _season_terms((m0[1] - 0.5) / 12)
    s1 = _season_terms((m1[1] - 0.5) / 12)
    c0, h0 = _degree_days(t0)
    c1, h1 = _degree_days(t1)
    return [
        float(_month_index(m1) - _month_index(m0)),
        *(b - a for a, b in zip(s0, s1)),
        float(m1[0] - m0[0]),  # Nowruz crossings
        c1 - c0,
        h1 - h0,
    ]


def build_monthly_outlook(
    daily: list[tuple[date, float, float, float]],
    temps: dict[date, float],
    forecast_days: set[date],
    today: date,
    horizon: int = HORIZON_MONTHS,
) -> MonthlyOutlook:
    month_price = monthly_prices(daily)
    month_temp = monthly_observed_temperature(temps, forecast_days)
    months = sorted(month_price)
    if len(months) < MONTHLY_MIN_TRAINING_MONTHS + 6:
        return MonthlyOutlook(status="insufficient_data", reason="price_history", months_used=len(months))

    columns = {name: [MONTHLY_FEATURES.index(f) for f in feats] for name, feats in REGRESSION_VARIANTS.items()}
    last_index = _month_index(months[-1])

    def weight(m: JMonth) -> float:
        return math.exp((_month_index(m) - last_index) * 30.4 / RECENCY_TAU_DAYS)

    def fit(train: list[JMonth]) -> dict[str, list[float] | None]:
        acc = _Accumulator(len(MONTHLY_FEATURES))
        for i, a in enumerate(train):
            for b in train[i + 1 :]:
                if _month_index(b) - _month_index(a) > horizon:
                    break
                if a in month_temp and b in month_temp:
                    x = _month_features(a, month_temp[a], b, month_temp[b])
                    acc.add(x, math.log(month_price[b][0]) - math.log(month_price[a][0]), weight(b))
        return {name: acc.solve(cols) for name, cols in columns.items()}

    def predict(model: str, origin: JMonth, target: JMonth, t0: float, t1: float, coefs, drift_per_month: float) -> float | None:
        p0 = month_price[origin][0]
        h = _month_index(target) - _month_index(origin)
        if model == "naive":
            return p0
        if model == "drift":
            return p0 * math.exp(drift_per_month * h)
        beta = coefs.get(model)
        if beta is None:
            return None
        x = _month_features(origin, t0, target, t1)
        return p0 * math.exp(sum(b * x[c] for b, c in zip(beta, columns[model])))

    def drift_for(origin: JMonth, train: list[JMonth]) -> float:
        back = [m for m in train if 11 <= _month_index(origin) - _month_index(m) <= 13]
        if not back:
            return 0.0
        m = back[0]
        return (math.log(month_price[origin][0]) - math.log(month_price[m][0])) / (_month_index(origin) - _month_index(m))

    # ---- walk-forward: refit at every month-end origin with >= 3 years behind it
    models = [*BASELINES, *REGRESSION_VARIANTS]
    records: dict[str, list[tuple[str, float, float, float]]] = {m: [] for m in models}
    residuals: dict[str, dict[str, list[float]]] = {m: {} for m in models}
    origins = [m for k, m in enumerate(months) if k >= MONTHLY_MIN_TRAINING_MONTHS and k < len(months) - 1]
    for origin in origins:
        train = [m for m in months if _month_index(m) <= _month_index(origin)]
        if origin not in month_temp:
            continue
        coefs = fit(train)
        normals = temperature_normals(month_temp, up_to=origin)
        drift = drift_for(origin, train)
        for target in months:
            h = _month_index(target) - _month_index(origin)
            if h < 1 or h > horizon or target[1] not in normals:
                continue
            # No look-ahead: the target month's temperature is its normal as
            # known at the origin, as it would be for a live forecast.
            t1 = normals[target[1]]
            actual = month_price[target][0]
            for model in models:
                pred = predict(model, origin, target, month_temp[origin], t1, coefs, drift)
                if pred is None:
                    continue
                records[model].append((f"h{h}", actual, pred, month_price[origin][0]))
                residuals[model].setdefault(f"h{h}", []).append(math.log(actual) - math.log(pred))

    scores = sorted((_score(m, r) for m, r in records.items() if len(r) >= 30), key=lambda s: s.mape)
    if not scores:
        return MonthlyOutlook(status="insufficient_data", reason="validation", months_used=len(months))
    selected = select_model(scores)

    # ---- final fit and outlook from the latest month (possibly in progress)
    coefs = fit(months)
    normals = temperature_normals(month_temp)
    origin = months[-1]
    origin_days = jalali_month_days(origin)
    t_origin = month_temp.get(origin)
    if t_origin is None:
        estimate = [temps.get(d, normals.get(origin[1])) for d in origin_days if d <= today]
        estimate = [t for t in estimate if t is not None]
        t_origin = statistics.fmean(estimate) if estimate else normals.get(origin[1])
    if t_origin is None:
        return MonthlyOutlook(status="insufficient_data", reason="temperature_history", months_used=len(months))
    drift = drift_for(origin, months)

    def outlook_with(model: str) -> list[MonthPoint]:
        out: list[MonthPoint] = []
        for h in range(1, horizon + 1):
            target = _from_index(_month_index(origin) + h)
            normal = normals.get(target[1])
            if normal is None:
                break
            target_days = jalali_month_days(target)
            covered = [temps[d] for d in target_days if d in forecast_days]
            t1 = statistics.fmean(covered + [normal] * (len(target_days) - len(covered))) if covered else normal
            pred = predict(model, origin, target, t_origin, t1, coefs, drift)
            if pred is None:
                break
            contributions: dict[str, float] = {}
            if model in REGRESSION_VARIANTS and coefs[model] is not None:
                coef_map = dict(zip(REGRESSION_VARIANTS[model], coefs[model]))  # type: ignore[arg-type]
                x = _month_features(origin, t_origin, target, t1)
                contributions = {
                    k: 100 * (math.exp(v) - 1) for k, v in _contributions(MONTHLY_FEATURES, coef_map, x).items()
                }
            elif model == "drift":
                contributions = {"drift": 100 * (pred / month_price[origin][0] - 1)}
            resid = residuals[model].get(f"h{h}") or [0.0]
            out.append(
                MonthPoint(
                    month=target,
                    horizon_months=h,
                    price=pred,
                    low=pred * math.exp(_quantile(resid, INTERVAL_QUANTILES[0])),
                    high=pred * math.exp(_quantile(resid, INTERVAL_QUANTILES[1])),
                    t_mean=t1,
                    t_source="forecast+normal" if covered else "normal",
                    t_normal=normal,
                    contributions_pct=contributions,
                )
            )
        return out

    points_by_model = {s.model: outlook_with(s.model) for s in scores}

    selected_coefs = coefs.get(selected) if selected in REGRESSION_VARIANTS else None
    # The in-progress month has fewer than MONTH_MIN_TEMP_DAYS observed days, so
    # it gets the same estimate the outlook itself starts from (observed days
    # so far, then forecast/normal) - otherwise its point drops out of the
    # temperature chart and the month axis skips it.
    history = [
        MonthHistory(
            month=m,
            price=month_price[m][0],
            trading_days=month_price[m][1],
            t_mean=month_temp.get(m, t_origin if m == origin else None),
        )
        for m in months[-24:]
    ]
    return MonthlyOutlook(
        status="ok",
        origin=origin,
        origin_price=month_price[origin][0],
        origin_trading_days=month_price[origin][1],
        origin_partial=jalali_month_of(today) == origin,
        history=history,
        points=points_by_model[selected],
        points_by_model=points_by_model,
        coefficients=dict(zip(REGRESSION_VARIANTS[selected], selected_coefs)) if selected_coefs else {},
        scores=scores,
        selected_model=selected,
        validation_origins=len(origins),
        validation_start=origins[0] if origins else None,
        validation_end=origins[-1] if origins else None,
        months_used=len(months),
        temperature_normals=normals,
    )
