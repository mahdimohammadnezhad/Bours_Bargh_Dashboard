"""Decision-support insight generation (docs brief section 16 + 21).

Every insight here must be traceable to a number computed from real data in
the request - no template text is emitted unless the underlying calculation
actually ran. Section 48 of the brief bans certainty language ("will
definitely rise"); the phrasing below sticks to descriptive/statistical
statements ("is in the Nth percentile", "deviated Xσ") which is what the
brief's own examples use.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analytics.stats import percentile_rank, zscore_of_latest


@dataclass(frozen=True)
class Insight:
    text: str
    evidence: dict[str, float | str]


def build_insights(
    price_series: list[float],
    volume_series: list[float] | None,
    lookback_label: str,
    volume_zscore_window: int = 30,
) -> list[Insight]:
    insights: list[Insight] = []

    if len(price_series) >= 5:
        latest_price = price_series[-1]
        price_pctl = percentile_rank(latest_price, price_series)
        insights.append(
            Insight(
                text=f"Current price is in the {_ordinal(price_pctl)} percentile of {lookback_label}.",
                evidence={"price_percentile": round(price_pctl, 1), "latest_price": latest_price},
            )
        )

    if volume_series and len(volume_series) >= volume_zscore_window + 1:
        z = zscore_of_latest(volume_series, volume_zscore_window)
        if z is not None:
            direction = "above" if z >= 0 else "below"
            insights.append(
                Insight(
                    text=(
                        f"Current trading volume is {abs(z):.1f} standard deviations {direction} "
                        f"its trailing {volume_zscore_window}-period average."
                    ),
                    evidence={"volume_zscore": round(z, 2), "window": volume_zscore_window},
                )
            )

    if volume_series and len(price_series) >= 2 and len(volume_series) >= 2:
        price_delta = price_series[-1] - price_series[-2]
        volume_delta = volume_series[-1] - volume_series[-2]
        if price_delta > 0 and volume_delta < 0:
            insights.append(
                Insight(
                    text=(
                        "Price increased while volume decreased on the latest tick, "
                        "indicating weak confirmation of the recent movement."
                    ),
                    evidence={"price_delta": price_delta, "volume_delta": volume_delta},
                )
            )
        elif price_delta < 0 and volume_delta > 0:
            insights.append(
                Insight(
                    text=(
                        "Price decreased while volume increased on the latest tick, "
                        "indicating stronger participation behind the recent decline."
                    ),
                    evidence={"price_delta": price_delta, "volume_delta": volume_delta},
                )
            )

    return insights


def _ordinal(percentile: float) -> str:
    n = round(percentile)
    suffix = "th"
    if n % 100 not in (11, 12, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
