"""Descriptive and rolling statistics over plain float series.

Deliberately stdlib-only (no numpy/pandas) - the series involved here are at
most a few thousand points (one instrument's ticks over a lookback window),
so the `statistics` module is fast enough, and it keeps the dependency list
honest per docs/ARCHITECTURE.md ("don't introduce ML/heavy deps until they
demonstrably earn their place").
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class DescriptiveStats:
    count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    std_dev: float
    coefficient_of_variation: float | None  # std/mean; None if mean == 0
    p10: float
    p25: float
    p75: float
    p90: float


def descriptive_stats(values: list[float]) -> DescriptiveStats:
    if not values:
        raise ValueError("descriptive_stats requires at least one value")

    mean = statistics.fmean(values)
    std_dev = statistics.pstdev(values) if len(values) > 1 else 0.0
    quantile_points = _percentiles(values, [10, 25, 75, 90])

    return DescriptiveStats(
        count=len(values),
        mean=mean,
        median=statistics.median(values),
        minimum=min(values),
        maximum=max(values),
        std_dev=std_dev,
        coefficient_of_variation=(std_dev / mean) if mean != 0 else None,
        p10=quantile_points[10],
        p25=quantile_points[25],
        p75=quantile_points[75],
        p90=quantile_points[90],
    )


def _percentiles(values: list[float], percentiles: list[int]) -> dict[int, float]:
    """Linear-interpolation percentiles (matches numpy's default 'linear' method)."""
    ordered = sorted(values)
    n = len(ordered)
    out: dict[int, float] = {}
    for p in percentiles:
        if n == 1:
            out[p] = ordered[0]
            continue
        rank = (p / 100) * (n - 1)
        lower = int(rank)
        upper = min(lower + 1, n - 1)
        frac = rank - lower
        out[p] = ordered[lower] + (ordered[upper] - ordered[lower]) * frac
    return out


def percentile_rank(value: float, series: list[float]) -> float:
    """Percentage of `series` that is <= value. 0-100 scale.

    Used for statements like "current price is in the 92nd percentile of the
    last N observations" (see docs/ARCHITECTURE.md decision-support spec).
    """
    if not series:
        raise ValueError("percentile_rank requires a non-empty series")
    ordered = sorted(series)
    count_le = bisect.bisect_right(ordered, value)
    return 100.0 * count_le / len(ordered)


def rolling_mean(values: list[float], window: int) -> list[float | None]:
    """Trailing rolling mean, aligned to the input (None until `window` points exist)."""
    if window < 1:
        raise ValueError("window must be >= 1")
    out: list[float | None] = [None] * len(values)
    running_sum = 0.0
    for i, v in enumerate(values):
        running_sum += v
        if i >= window:
            running_sum -= values[i - window]
        if i >= window - 1:
            out[i] = running_sum / window
    return out


def rolling_std(values: list[float], window: int) -> list[float | None]:
    """Trailing rolling population std dev, aligned to the input."""
    if window < 2:
        raise ValueError("window must be >= 2")
    out: list[float | None] = [None] * len(values)
    for i in range(window - 1, len(values)):
        window_slice = values[i - window + 1 : i + 1]
        out[i] = statistics.pstdev(window_slice)
    return out


def zscore_of_latest(values: list[float], window: int) -> float | None:
    """z-score of the last value against the mean/std of the preceding `window` values.

    Returns None if there isn't enough history or the window is flat (std == 0).
    """
    if len(values) < window + 1:
        return None
    history = values[-(window + 1) : -1]
    mean = statistics.fmean(history)
    std = statistics.pstdev(history)
    if std == 0:
        return None
    return (values[-1] - mean) / std


def pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous
