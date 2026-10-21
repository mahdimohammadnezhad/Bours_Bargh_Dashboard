"""Analytics endpoints.

`/overview` and `/anomalies` work per instrument over stored quotes (see
app/services/analytics_service.py).

`/forecast`, `/patterns` and `/recommendations` work at market level on the
power market's daily base-load VWAP and the national temperature series
(see app/services/forecast_service.py and app/analytics/{forecast,patterns,
recommendation}.py). If the history or the temperatures are not there yet
they answer `status: "insufficient_data"` with a reason - never invented
numbers.
"""

from datetime import date, timedelta

import jdatetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.forecast import DailyPoint, ModelScore, MonthPoint
from app.database.session import get_db
from app.schemas.analytics import (
    AnalogueOut,
    AnalyticsOverviewOut,
    AnomaliesOut,
    DailyForecastOut,
    DailyForecastPointOut,
    DayPriceOut,
    EvidenceOut,
    ForecastOut,
    MonthForecastPointOut,
    MonthHistoryOut,
    MonthlyOutlookOut,
    MonthPatternOut,
    MonthTransitionOut,
    ModelScoreOut,
    PatternsOut,
    RecommendationOut,
    SeriesInfo,
    TemperatureBinOut,
    TemperatureDayOut,
    ValidationOut,
    WeekdayPatternOut,
)
from app.services import analytics_service, forecast_service
from app.services.forecast_service import HISTORY_TRADING_DAYS, AnalysisBundle
from app.services.historical_ingestion import SOURCE_ID

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

MARKET_QUERY = Query(
    forecast_service.DEFAULT_MARKET,
    pattern="^(" + "|".join(forecast_service.MARKETS) + ")$",
    description="free_forward (Free Power forward base load, default), free_physical, or power (main market base load)",
)


@router.get("/overview", response_model=AnalyticsOverviewOut)
async def analytics_overview(
    source_id: str = Query(...),
    symbol: str = Query(..., description="source-specific symbol, as returned by /api/market/quotes"),
    lookback_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverviewOut:
    return await analytics_service.get_overview(db, source_id, symbol, lookback_days)


@router.get("/anomalies", response_model=AnomaliesOut)
async def anomalies(
    source_id: str = Query(...),
    symbol: str = Query(..., description="source-specific symbol, as returned by /api/market/quotes"),
    lookback_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> AnomaliesOut:
    return await analytics_service.get_anomalies(db, source_id, symbol, lookback_days)


# ---------------------------------------------------------------- market-level


def _jalali(d: date) -> str:
    return jdatetime.date.fromgregorian(date=d).strftime("%Y/%m/%d")


def _month_label(month: tuple[int, int]) -> str:
    return f"{month[0]}/{month[1]:02d}"


def _series(bundle: AnalysisBundle) -> SeriesInfo:
    rows = bundle.daily_rows
    return SeriesInfo(
        market=bundle.market,
        source_id=SOURCE_ID,
        symbol=bundle.symbol,
        unit="Rials/kWh",
        first_day=rows[0][0] if rows else None,
        last_day=rows[-1][0] if rows else None,
        trading_days=len(rows),
    )


def _scores(scores: list[ModelScore]) -> list[ModelScoreOut]:
    return [
        ModelScoreOut(
            model=s.model,
            n=s.n,
            mae=s.mae,
            mape=s.mape,
            directional_accuracy=s.directional_accuracy,
            by_horizon=s.by_horizon,
        )
        for s in scores
    ]


def _month_points(points: list[MonthPoint]) -> list[MonthForecastPointOut]:
    return [
        MonthForecastPointOut(
            label=_month_label(p.month),
            year=p.month[0],
            month=p.month[1],
            horizon_months=p.horizon_months,
            price=p.price,
            low=p.low,
            high=p.high,
            t_mean=p.t_mean,
            t_source=p.t_source,
            t_normal=p.t_normal,
            contributions_pct=p.contributions_pct,
        )
        for p in points
    ]


def _day_points(points: list[DailyPoint]) -> list[DailyForecastPointOut]:
    return [
        DailyForecastPointOut(
            day=p.day,
            jalali=_jalali(p.day),
            horizon_days=p.horizon_days,
            price=p.price,
            low=p.low,
            high=p.high,
            t7=p.t7,
            contributions_pct=p.contributions_pct,
        )
        for p in points
    ]


@router.get("/forecast", response_model=ForecastOut)
async def forecast(market: str = MARKET_QUERY, db: AsyncSession = Depends(get_db)) -> ForecastOut:
    bundle = await forecast_service.get_analysis(db, market)
    daily, monthly = bundle.daily, bundle.monthly
    rows = bundle.daily_rows[-HISTORY_TRADING_DAYS:]
    window_start = rows[0][0] if rows else bundle.today - timedelta(days=180)
    status = "ok" if monthly.status == "ok" or daily.status == "ok" else "insufficient_data"

    monthly_out = MonthlyOutlookOut(status=monthly.status, reason=monthly.reason, months_used=monthly.months_used)
    if monthly.status == "ok" and monthly.origin is not None:
        monthly_out = MonthlyOutlookOut(
            status="ok",
            origin_label=_month_label(monthly.origin),
            origin_price=monthly.origin_price,
            origin_trading_days=monthly.origin_trading_days,
            origin_partial=monthly.origin_partial,
            history=[
                MonthHistoryOut(
                    label=_month_label(h.month),
                    year=h.month[0],
                    month=h.month[1],
                    price=h.price,
                    trading_days=h.trading_days,
                    t_mean=h.t_mean,
                )
                for h in monthly.history
            ],
            points=_month_points(monthly.points),
            models={model: _month_points(points) for model, points in monthly.points_by_model.items()},
            coefficients=monthly.coefficients,
            validation=ValidationOut(
                origins=monthly.validation_origins,
                start=_month_label(monthly.validation_start) if monthly.validation_start else None,
                end=_month_label(monthly.validation_end) if monthly.validation_end else None,
                selected_model=monthly.selected_model,
                scores=_scores(monthly.scores),
            ),
            months_used=monthly.months_used,
        )

    daily_out = DailyForecastOut(status=daily.status, reason=daily.reason)
    if daily.status == "ok":
        daily_out = DailyForecastOut(
            status="ok",
            points=_day_points(daily.points),
            models={model: _day_points(points) for model, points in daily.points_by_model.items()},
            validation=ValidationOut(
                origins=daily.validation_origins,
                start=_jalali(daily.validation_start) if daily.validation_start else None,
                end=_jalali(daily.validation_end) if daily.validation_end else None,
                selected_model=daily.selected_model,
                scores=_scores(daily.scores),
            ),
        )

    return ForecastOut(
        status=status,
        generated_at=bundle.generated_at,
        series=_series(bundle),
        last_day=bundle.daily_rows[-1][0] if bundle.daily_rows else None,
        last_price=bundle.daily_rows[-1][1] if bundle.daily_rows else None,
        interval_pct=80,
        history=[DayPriceOut(day=d, jalali=_jalali(d), price=p) for d, p, _, _ in rows],
        temperature=[
            TemperatureDayOut(day=d, t_mean=t, is_forecast=d in bundle.forecast_days)
            for d, t in sorted(bundle.temps.items())
            if d >= window_start
        ],
        monthly=monthly_out,
        daily=daily_out,
    )


@router.get("/patterns", response_model=PatternsOut)
async def patterns(market: str = MARKET_QUERY, db: AsyncSession = Depends(get_db)) -> PatternsOut:
    bundle = await forecast_service.get_analysis(db, market)
    p = bundle.patterns
    if p.status != "ok":
        return PatternsOut(status=p.status, reason=p.reason, generated_at=bundle.generated_at, series=_series(bundle))
    return PatternsOut(
        status="ok",
        generated_at=bundle.generated_at,
        series=_series(bundle),
        seasonal=[MonthPatternOut(**vars(m)) for m in p.seasonal],
        seasonal_years=p.seasonal_years,
        transitions=[MonthTransitionOut(**vars(t)) for t in p.transitions],
        weekday=[WeekdayPatternOut(**vars(w)) for w in p.weekday],
        weekday_since=p.weekday_since,
        temperature_bins=[TemperatureBinOut(**vars(b)) for b in p.temperature_bins],
        temperature_correlation=p.temperature_correlation,
        temperature_points=p.temperature_points,
        current_day=p.current_day,
        current_features=p.current_features,
        analogues=[
            AnalogueOut(
                day=a.day,
                jalali=_jalali(a.day),
                similarity=a.similarity,
                price=a.price,
                features=a.features,
                outcomes_pct=a.outcomes_pct,
            )
            for a in p.analogues
        ],
        analogue_summary=p.analogue_summary,
    )


@router.get("/recommendations", response_model=RecommendationOut)
async def recommendations(market: str = MARKET_QUERY, db: AsyncSession = Depends(get_db)) -> RecommendationOut:
    bundle = await forecast_service.get_analysis(db, market)
    r = bundle.recommendation
    return RecommendationOut(
        status=r.status,
        reason=r.reason,
        generated_at=bundle.generated_at,
        series=_series(bundle),
        as_of=r.as_of,
        signal=r.signal,
        score=r.score,
        agreement_pct=r.agreement_pct,
        volatility_percentile=bundle.volatility_percentile,
        caution=r.caution,
        evidence=[EvidenceOut(**vars(e)) for e in r.evidence],
    )
