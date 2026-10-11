"""Market regime classification (docs brief section 14).

The brief is explicit: "Do not claim causality without evidence" and
"clearly distinguish Observed from Model-derived from Interpretation".
RegimeResult keeps those three tiers as separate fields rather than one
blended paragraph, so the API/UI can label them distinctly instead of
presenting a rule-of-thumb label as if it were a measured fact.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from app.analytics.stats import percentile_rank

HIGH_PERCENTILE = 90.0
LOW_PERCENTILE = 10.0
ABNORMAL_PERCENTILE = 97.0
VOLATILITY_ZSCORE_THRESHOLD = 2.0


@dataclass(frozen=True)
class RegimeResult:
    observed: dict[str, float]
    labels: list[str]  # model-derived, rule-based tags
    interpretation: str


def _has_variation(series: list[float]) -> bool:
    return statistics.pstdev(series) > 0 if len(series) > 1 else False


def classify_regime(
    price_series: list[float],
    volume_series: list[float] | None,
    recent_volatility: float | None,
    volatility_history: list[float] | None,
) -> RegimeResult:
    """
    price_series: full lookback-window price history, most recent last.
    volume_series: same-length volume history, if available.
    recent_volatility: latest rolling std-dev of price (e.g. last 20 points).
    volatility_history: series of that same rolling std-dev over time, used to
        judge whether *current* volatility is itself unusual.
    """
    latest_price = price_series[-1]
    price_pctl = percentile_rank(latest_price, price_series)

    observed: dict[str, float] = {"price_percentile": round(price_pctl, 1)}
    labels: list[str] = []

    # A percentile rank is only meaningful when the series actually varies -
    # in a perfectly flat series the latest point trivially ties for 100th
    # percentile, which would otherwise mislabel "no movement at all" as
    # "high_price"/"abnormal_price".
    if _has_variation(price_series):
        if price_pctl >= HIGH_PERCENTILE:
            labels.append("high_price")
        elif price_pctl <= LOW_PERCENTILE:
            labels.append("low_price")

        if price_pctl >= ABNORMAL_PERCENTILE or price_pctl <= (100 - ABNORMAL_PERCENTILE):
            labels.append("abnormal_price")

    volume_pctl: float | None = None
    if volume_series and len(volume_series) >= 5:
        volume_pctl = percentile_rank(volume_series[-1], volume_series)
        observed["volume_percentile"] = round(volume_pctl, 1)
        if _has_variation(volume_series) and volume_pctl >= HIGH_PERCENTILE:
            labels.append("high_volume")

    vol_zscore: float | None = None
    if recent_volatility is not None and volatility_history and len(volatility_history) >= 5:
        hist_mean = statistics.fmean(volatility_history)
        hist_std = statistics.pstdev(volatility_history)
        if hist_std > 0:
            vol_zscore = (recent_volatility - hist_mean) / hist_std
            observed["volatility_zscore"] = round(vol_zscore, 2)
            if vol_zscore >= VOLATILITY_ZSCORE_THRESHOLD:
                labels.append("high_volatility")

    if not labels:
        labels.append("normal")

    interpretation = _build_interpretation(labels, observed)

    return RegimeResult(observed=observed, labels=labels, interpretation=interpretation)


def _build_interpretation(labels: list[str], observed: dict[str, float]) -> str:
    if labels == ["normal"]:
        return (
            "Price, volume, and volatility are all within their typical historical "
            "range for the available lookback window - no regime flag raised."
        )

    parts: list[str] = []
    if "high_price" in labels:
        parts.append(f"price is elevated (percentile {observed.get('price_percentile')})")
    if "low_price" in labels:
        parts.append(f"price is depressed (percentile {observed.get('price_percentile')})")
    if "high_volatility" in labels:
        parts.append(f"volatility is elevated ({observed.get('volatility_zscore')}σ vs its own history)")
    if "high_volume" in labels:
        parts.append(f"volume is elevated (percentile {observed.get('volume_percentile')})")
    if "abnormal_price" in labels:
        parts.append("price sits in an extreme tail of the observed lookback window")

    joined = "; ".join(parts)
    return (
        f"Rule-based classification against the available lookback window: {joined}. "
        "This is a descriptive/model-derived label, not a causal explanation or a forecast."
    )
