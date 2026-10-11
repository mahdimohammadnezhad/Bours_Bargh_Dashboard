from datetime import date, datetime

from pydantic import BaseModel


class DescriptiveStatsOut(BaseModel):
    count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    std_dev: float
    coefficient_of_variation: float | None
    p10: float
    p25: float
    p75: float
    p90: float


class RegimeOut(BaseModel):
    observed: dict[str, float]
    labels: list[str]
    interpretation: str


class InsightOut(BaseModel):
    text: str
    evidence: dict[str, float | str]


class AnalyticsOverviewOut(BaseModel):
    status: str  # "ok" | "insufficient_data"
    source_id: str
    source_symbol: str
    lookback_start: datetime | None = None
    lookback_end: datetime | None = None
    available_points: int
    min_required_points: int
    price_stats: DescriptiveStatsOut | None = None
    volume_stats: DescriptiveStatsOut | None = None
    regime: RegimeOut | None = None
    insights: list[InsightOut] = []


class AnomalyOut(BaseModel):
    timestamp: datetime
    metric: str
    source: str
    method: str
    observed_value: float
    expected_range: tuple[float, float] | None
    severity: str
    explanation: str


class AnomaliesOut(BaseModel):
    status: str
    source_id: str
    source_symbol: str
    available_points: int
    min_required_points: int
    anomalies: list[AnomalyOut] = []


# --- forecast / patterns / recommendations (market-level: base-load daily VWAP)


class SeriesInfo(BaseModel):
    source_id: str
    symbol: str
    unit: str
    first_day: date | None
    last_day: date | None
    trading_days: int


class ModelScoreOut(BaseModel):
    model: str
    n: int
    mae: float
    mape: float
    directional_accuracy: float | None
    by_horizon: dict[str, dict[str, float | int | None]]


class ValidationOut(BaseModel):
    origins: int
    start: str | None
    end: str | None
    selected_model: str | None  # default: lowest validated MAPE
    scores: list[ModelScoreOut]


class DayPriceOut(BaseModel):
    day: date
    jalali: str
    price: float


class TemperatureDayOut(BaseModel):
    day: date
    t_mean: float
    is_forecast: bool


class DailyForecastPointOut(BaseModel):
    day: date
    jalali: str
    horizon_days: int
    price: float
    low: float
    high: float
    t7: float | None
    contributions_pct: dict[str, float]


class DailyForecastOut(BaseModel):
    status: str
    reason: str | None = None
    points: list[DailyForecastPointOut] = []  # the selected (default) model's
    models: dict[str, list[DailyForecastPointOut]] = {}  # every validated model's
    validation: ValidationOut | None = None


class MonthHistoryOut(BaseModel):
    label: str
    year: int
    month: int
    price: float
    trading_days: int
    t_mean: float | None


class MonthForecastPointOut(BaseModel):
    label: str
    year: int
    month: int
    horizon_months: int
    price: float
    low: float
    high: float
    t_mean: float
    t_source: str
    t_normal: float
    contributions_pct: dict[str, float]


class MonthlyOutlookOut(BaseModel):
    status: str
    reason: str | None = None
    origin_label: str | None = None
    origin_price: float | None = None
    origin_trading_days: int = 0
    origin_partial: bool = False
    history: list[MonthHistoryOut] = []
    points: list[MonthForecastPointOut] = []  # the selected (default) model's
    models: dict[str, list[MonthForecastPointOut]] = {}  # every validated model's
    coefficients: dict[str, float] = {}
    validation: ValidationOut | None = None
    months_used: int = 0


class ForecastOut(BaseModel):
    status: str
    generated_at: datetime
    series: SeriesInfo
    last_day: date | None
    last_price: float | None
    interval_pct: int
    history: list[DayPriceOut]
    temperature: list[TemperatureDayOut]
    monthly: MonthlyOutlookOut
    daily: DailyForecastOut


class MonthPatternOut(BaseModel):
    month: int
    mean_deviation_pct: float
    std_pct: float
    years: int
    trading_days: int
    consistency: float


class MonthTransitionOut(BaseModel):
    from_month: int
    to_month: int
    mean_change_pct: float
    median_change_pct: float
    share_up: float
    years: int


class WeekdayPatternOut(BaseModel):
    weekday: int
    mean_change_pct: float
    share_up: float
    n: int


class TemperatureBinOut(BaseModel):
    low: float
    high: float
    mean_deviation_pct: float
    n: int


class AnalogueOut(BaseModel):
    day: date
    jalali: str
    similarity: float
    price: float
    features: dict[str, float]
    outcomes_pct: dict[str, float]


class PatternsOut(BaseModel):
    status: str
    reason: str | None = None
    generated_at: datetime
    series: SeriesInfo
    seasonal: list[MonthPatternOut] = []
    seasonal_years: list[int] = []
    transitions: list[MonthTransitionOut] = []
    weekday: list[WeekdayPatternOut] = []
    weekday_since: date | None = None
    temperature_bins: list[TemperatureBinOut] = []
    temperature_correlation: float | None = None
    temperature_points: int = 0
    current_day: date | None = None
    current_features: dict[str, float] = {}
    analogues: list[AnalogueOut] = []
    analogue_summary: dict[str, float | int | None] = {}


class EvidenceOut(BaseModel):
    key: str
    kind: str
    direction: int
    strength: float
    value: float | None
    threshold: float | None
    detail: dict[str, float | int | str | None]


class RecommendationOut(BaseModel):
    status: str
    reason: str | None = None
    generated_at: datetime
    series: SeriesInfo
    as_of: date | None = None
    horizon: str = "1-3 months"
    signal: str | None = None
    score: float | None = None
    agreement_pct: float | None = None
    volatility_percentile: float | None = None
    caution: list[str] = []
    evidence: list[EvidenceOut] = []
