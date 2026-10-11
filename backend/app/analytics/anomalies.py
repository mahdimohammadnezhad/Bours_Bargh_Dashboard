"""Anomaly detection over a single metric's time series.

Implements the four required detectors from docs/ARCHITECTURE.md / the
project brief (rolling z-score, IQR, robust z-score, percentile-based).
Isolation Forest / LOF were left out deliberately: they are listed as
optional in the brief, and with the sparse data this project currently has
(no verified live feed yet - see docs/DATA_SOURCES.md) they would either be
untrainable or overfit to noise. Add them once real ingestion is flowing and
a lookback window of meaningful size actually exists.

Every detector operates on a plain (timestamps, values) series for one
metric and yields Anomaly records - see docs/ARCHITECTURE.md for the schema
this maps onto (severity, observed value, expected range, explanation,
source all required per the brief, section 15).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Anomaly:
    timestamp: datetime
    metric: str
    source: str
    method: str
    observed_value: float
    expected_range: tuple[float, float] | None
    severity: Severity
    explanation: str


def _severity_from_ratio(ratio: float) -> Severity:
    """ratio = how many multiples past the flagging threshold this point is."""
    if ratio >= 2.0:
        return Severity.HIGH
    if ratio >= 1.3:
        return Severity.MEDIUM
    return Severity.LOW


def rolling_zscore_anomalies(
    timestamps: list[datetime],
    values: list[float],
    metric: str,
    source: str,
    window: int = 20,
    threshold: float = 3.0,
) -> list[Anomaly]:
    out: list[Anomaly] = []
    if len(values) <= window:
        return out
    for i in range(window, len(values)):
        history = values[i - window : i]
        mean = statistics.fmean(history)
        std = statistics.pstdev(history)
        if std == 0:
            continue
        z = (values[i] - mean) / std
        if abs(z) >= threshold:
            low, high = mean - threshold * std, mean + threshold * std
            out.append(
                Anomaly(
                    timestamp=timestamps[i],
                    metric=metric,
                    source=source,
                    method="rolling_zscore",
                    observed_value=values[i],
                    expected_range=(low, high),
                    severity=_severity_from_ratio(abs(z) / threshold),
                    explanation=(
                        f"{metric} deviated {z:+.2f} standard deviations from its "
                        f"trailing {window}-point mean ({mean:.4g}, std {std:.4g})."
                    ),
                )
            )
    return out


def iqr_anomalies(
    timestamps: list[datetime],
    values: list[float],
    metric: str,
    source: str,
    k: float = 1.5,
) -> list[Anomaly]:
    out: list[Anomaly] = []
    if len(values) < 4:
        return out
    q1, q3 = statistics.quantiles(values, n=4)[0], statistics.quantiles(values, n=4)[2]
    iqr = q3 - q1
    if iqr == 0:
        return out
    lower, upper = q1 - k * iqr, q3 + k * iqr
    for ts, v in zip(timestamps, values):
        if v < lower or v > upper:
            distance = (lower - v) if v < lower else (v - upper)
            ratio = distance / (k * iqr)
            out.append(
                Anomaly(
                    timestamp=ts,
                    metric=metric,
                    source=source,
                    method="iqr",
                    observed_value=v,
                    expected_range=(lower, upper),
                    severity=_severity_from_ratio(1 + ratio),
                    explanation=(
                        f"{metric}={v:.4g} is outside the IQR fence "
                        f"[{lower:.4g}, {upper:.4g}] (Q1={q1:.4g}, Q3={q3:.4g}, k={k})."
                    ),
                )
            )
    return out


def robust_zscore_anomalies(
    timestamps: list[datetime],
    values: list[float],
    metric: str,
    source: str,
    threshold: float = 3.5,
) -> list[Anomaly]:
    """Median Absolute Deviation based z-score - less sensitive to the outliers
    it's trying to detect than a plain mean/std z-score."""
    out: list[Anomaly] = []
    if len(values) < 4:
        return out
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    if mad == 0:
        return out
    for ts, v in zip(timestamps, values):
        modified_z = 0.6745 * (v - med) / mad
        if abs(modified_z) >= threshold:
            spread = threshold * mad / 0.6745
            out.append(
                Anomaly(
                    timestamp=ts,
                    metric=metric,
                    source=source,
                    method="robust_zscore",
                    observed_value=v,
                    expected_range=(med - spread, med + spread),
                    severity=_severity_from_ratio(abs(modified_z) / threshold),
                    explanation=(
                        f"{metric}={v:.4g} has a robust (MAD-based) z-score of "
                        f"{modified_z:+.2f} against a median of {med:.4g}."
                    ),
                )
            )
    return out


def percentile_anomalies(
    timestamps: list[datetime],
    values: list[float],
    metric: str,
    source: str,
    lower_pct: float = 1.0,
    upper_pct: float = 99.0,
) -> list[Anomaly]:
    out: list[Anomaly] = []
    if len(values) < 10:
        return out
    ordered = sorted(values)
    n = len(ordered)

    def pct(p: float) -> float:
        rank = (p / 100) * (n - 1)
        lo, hi = int(rank), min(int(rank) + 1, n - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)

    low_bound, high_bound = pct(lower_pct), pct(upper_pct)
    for ts, v in zip(timestamps, values):
        if v < low_bound or v > high_bound:
            out.append(
                Anomaly(
                    timestamp=ts,
                    metric=metric,
                    source=source,
                    method="percentile",
                    observed_value=v,
                    expected_range=(low_bound, high_bound),
                    severity=Severity.MEDIUM,
                    explanation=(
                        f"{metric}={v:.4g} falls outside the [{lower_pct:.0f}th, "
                        f"{upper_pct:.0f}th] percentile band [{low_bound:.4g}, {high_bound:.4g}]."
                    ),
                )
            )
    return out


def detect_all(
    timestamps: list[datetime],
    values: list[float],
    metric: str,
    source: str,
) -> list[Anomaly]:
    """Run every detector and merge results, deduplicated by (timestamp, method)."""
    results: list[Anomaly] = []
    results += rolling_zscore_anomalies(timestamps, values, metric, source)
    results += iqr_anomalies(timestamps, values, metric, source)
    results += robust_zscore_anomalies(timestamps, values, metric, source)
    results += percentile_anomalies(timestamps, values, metric, source)
    results.sort(key=lambda a: a.timestamp, reverse=True)
    return results
