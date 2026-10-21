"""Evidence-backed market signal (brief sections 20, 21 and 48).

Turns the forecast and pattern results into one of three signals for the
next 1-3 months - upward pressure, downward pressure or mixed - without
ever claiming certainty. Every input is an Evidence item carrying its own
number, the threshold that gave it a direction, a strength in [0, 1] taken
from that evidence's own historical track record, and whether it is
observed history or model output. The signal is the strength-weighted vote;
"agreement" is the share of directional strength that points the same way
as the signal. It is a consistency measure of the evidence, not a
probability of the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.analytics.forecast import DailyForecast, ModelScore, MonthlyOutlook, jalali_month_of
from app.analytics.patterns import PatternsResult

OUTLOOK_THRESHOLD_PCT = 2.0
SEASONAL_THRESHOLD_PCT = 2.0
SHORT_TERM_THRESHOLD_PCT = 1.0
ANALOGUE_UP_SHARE = 0.6
ANALOGUE_DOWN_SHARE = 0.4
SIGNAL_THRESHOLD = 0.3
MIN_DIRECTIONAL_EVIDENCE = 2
HIGH_VOLATILITY_PERCENTILE = 90.0


@dataclass
class Evidence:
    key: str
    kind: str  # "observed" | "model"
    direction: int  # -1, 0, +1
    strength: float  # 0..1, from this evidence's own track record
    value: float | None
    threshold: float | None
    detail: dict[str, float | int | str | None] = field(default_factory=dict)


@dataclass
class Recommendation:
    status: str
    reason: str | None = None
    as_of: date | None = None
    signal: str | None = None  # upward_pressure | downward_pressure | mixed
    score: float | None = None
    agreement_pct: float | None = None
    caution: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


def _direction(value: float, threshold: float) -> int:
    return 1 if value >= threshold else -1 if value <= -threshold else 0


def _score_for(scores: list[ModelScore], model: str | None) -> ModelScore | None:
    return next((s for s in scores if s.model == model), None)


def _directional_strength(score: ModelScore | None, horizon_key: str) -> float:
    """Validated direction hit-rate mapped to [0, 1]: 50% (a coin) -> 0, 100% -> 1."""
    if score is None:
        return 0.0
    accuracy = score.by_horizon.get(horizon_key, {}).get("directional_accuracy")
    if accuracy is None:
        return 0.0
    return max(0.0, min(1.0, (float(accuracy) - 50.0) / 50.0))


def build_recommendation(
    monthly: MonthlyOutlook,
    daily: DailyForecast,
    patterns: PatternsResult,
    volatility_percentile: float | None,
) -> Recommendation:
    if patterns.status != "ok":
        return Recommendation(status="insufficient_data", reason="inputs")
    # Young markets (Free Power) have no validated monthly outlook; the signal
    # then rests on the evidence that does exist instead of being invented.
    has_outlook = monthly.status == "ok" and bool(monthly.points) and monthly.origin_price is not None

    evidence: list[Evidence] = []
    selected_score = _score_for(monthly.scores, monthly.selected_model)

    # 1-2. Monthly outlook (model): next month and three months out.
    for h, key in ((1, "outlook_next_month"), (3, "outlook_3_months")) if has_outlook else ():
        point = next((p for p in monthly.points if p.horizon_months == h), None)
        if point is None:
            continue
        change = 100 * (point.price / monthly.origin_price - 1)
        evidence.append(
            Evidence(
                key=key,
                kind="model",
                direction=_direction(change, OUTLOOK_THRESHOLD_PCT),
                strength=_directional_strength(selected_score, f"h{h}"),
                value=change,
                threshold=OUTLOOK_THRESHOLD_PCT,
                detail={
                    "model": monthly.selected_model,
                    "price": point.price,
                    "low": point.low,
                    "high": point.high,
                    "month": f"{point.month[0]}/{point.month[1]:02d}",
                    "validated_direction_accuracy": (selected_score.by_horizon.get(f"h{h}", {}) or {}).get(
                        "directional_accuracy"
                    )
                    if selected_score
                    else None,
                },
            )
        )

    # 3. Historical month-to-month move from the current month (observed).
    if monthly.origin:
        current_month = monthly.origin[1]
    elif patterns.current_day:
        current_month = jalali_month_of(patterns.current_day)[1]
    else:
        current_month = None
    transition = next((t for t in patterns.transitions if t.from_month == current_month), None)
    if transition is not None:
        up = transition.share_up
        consistency = up if transition.mean_change_pct > 0 else 1 - up
        evidence.append(
            Evidence(
                key="seasonal_transition",
                kind="observed",
                direction=_direction(transition.mean_change_pct, SEASONAL_THRESHOLD_PCT),
                strength=max(0.0, (consistency - 0.5) * 2),
                value=transition.mean_change_pct,
                threshold=SEASONAL_THRESHOLD_PCT,
                detail={
                    "from_month": transition.from_month,
                    "to_month": transition.to_month,
                    "years": transition.years,
                    "years_up": round(up * transition.years),
                },
            )
        )

    # 4. Historical analogues (observed): what followed similar conditions.
    share_up = patterns.analogue_summary.get("share_up_20d")
    if isinstance(share_up, float):
        direction = 1 if share_up >= ANALOGUE_UP_SHARE else -1 if share_up <= ANALOGUE_DOWN_SHARE else 0
        evidence.append(
            Evidence(
                key="analogues_20d",
                kind="observed",
                direction=direction,
                strength=abs(share_up - 0.5) * 2,
                value=100 * share_up,
                threshold=100 * ANALOGUE_UP_SHARE,
                detail={
                    "n": patterns.analogue_summary.get("n"),
                    "median_change_pct": patterns.analogue_summary.get("median_20d_pct"),
                    "mean_similarity": patterns.analogue_summary.get("mean_similarity"),
                },
            )
        )

    # 5. Short-term model (next ~2 weeks). Only directional if a model that
    #    actually predicts moves validated best; "no change" carries no vote.
    if daily.status == "ok" and daily.points and daily.last_price:
        last = daily.points[-1]
        change = 100 * (last.price / daily.last_price - 1)
        daily_score = _score_for(daily.scores, daily.selected_model)
        evidence.append(
            Evidence(
                key="short_term",
                kind="model",
                direction=_direction(change, SHORT_TERM_THRESHOLD_PCT) if daily.selected_model != "naive" else 0,
                strength=_directional_strength(daily_score, "8-14") if daily.selected_model != "naive" else 0.0,
                value=change,
                threshold=SHORT_TERM_THRESHOLD_PCT,
                detail={
                    "model": daily.selected_model,
                    "low": last.low,
                    "high": last.high,
                    "horizon_days": last.horizon_days,
                },
            )
        )

    total = sum(e.strength for e in evidence)
    if total == 0:
        return Recommendation(
            status="ok",
            as_of=daily.last_day,
            signal="mixed",
            score=0.0,
            caution=[] if has_outlook else ["short_history"],
            evidence=evidence,
        )
    score = sum(e.direction * e.strength for e in evidence) / total
    signal = "upward_pressure" if score >= SIGNAL_THRESHOLD else "downward_pressure" if score <= -SIGNAL_THRESHOLD else "mixed"
    # One piece of evidence agreeing with itself is not "100% agreement":
    # a directional signal needs at least two independent directional items
    # (Free Power on 2026-10-21 had only the analogue vote).
    if sum(1 for e in evidence if e.direction != 0 and e.strength > 0) < MIN_DIRECTIONAL_EVIDENCE:
        signal = "mixed"

    agreement = None
    directional = [e for e in evidence if e.direction != 0 and e.strength > 0]
    if signal != "mixed" and directional:
        sign = 1 if signal == "upward_pressure" else -1
        agreeing = sum(e.strength for e in directional if e.direction == sign)
        agreement = 100 * agreeing / sum(e.strength for e in directional)

    caution: list[str] = []
    if volatility_percentile is not None and volatility_percentile >= HIGH_VOLATILITY_PERCENTILE:
        caution.append("high_volatility")
    if monthly.points and monthly.points[0].t_source == "normal":
        caution.append("temperature_from_normals")
    if monthly.origin_partial:
        caution.append("current_month_partial")
    if any(p.month[1] == 1 for p in monthly.points[:3]):
        caution.append("nowruz_reset_ahead")
    if not has_outlook:
        caution.append("short_history")

    return Recommendation(
        status="ok",
        as_of=daily.last_day,
        signal=signal,
        score=score,
        agreement_pct=agreement,
        caution=caution,
        evidence=evidence,
    )
