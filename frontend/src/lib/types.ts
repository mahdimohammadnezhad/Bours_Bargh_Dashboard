export type SourceStatus = "healthy" | "degraded" | "down" | "not_configured" | "unknown";

export interface SourceHealth {
  source_id: string;
  name: string;
  status: SourceStatus;
  last_success_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  consecutive_failures: number;
  latency_ms: number | null;
  stale_seconds: number | null;
}

export interface MarketStatus {
  is_active_session: boolean;
  server_time: string;
  sources: SourceHealth[];
}

export interface Quote {
  source_id: string;
  source_symbol: string;
  instrument_symbol: string | null;
  observed_at: string;
  last_price: number | null;
  close_price: number | null;
  price_change: number | null;
  price_change_percent: number | null;
  volume: number | null;
  value: number | null;
  transaction_count: number | null;
  is_stale: boolean;
  raw: Record<string, unknown> | null;
}

export interface CollectorLog {
  source_id: string;
  started_at: string;
  finished_at: string | null;
  status: "success" | "error" | "skipped" | "not_configured";
  http_status: number | null;
  latency_ms: number | null;
  records_fetched: number;
  records_inserted: number;
  records_skipped: number;
  error_message: string | null;
}

export interface Instrument {
  symbol: string;
  name: string;
  market_segment: string | null;
}

export interface PriceHistoryPoint {
  observed_at: string;
  last_price: number | null;
  volume: number | null;
  raw: Record<string, unknown> | null;
}

export interface PriceHistory {
  source_id: string;
  source_symbol: string;
  points: PriceHistoryPoint[];
}

export interface WsSnapshotMessage {
  type: "snapshot";
  server_time: string;
  sources: Array<{
    source_id: string;
    name: string;
    status: SourceStatus;
    last_success_at: string | null;
    last_error: string | null;
    last_error_at: string | null;
    consecutive_failures: number;
    latency_ms: number | null;
  }>;
  quotes: Array<{
    source_id: string;
    source_symbol: string;
    observed_at: string;
    last_price: number | null;
    volume: number | null;
    price_change_percent: number | null;
    raw?: Record<string, unknown> | null;
  }>;
}

export interface WsQuotesMessage {
  type: "quotes";
  source: string;
  server_time: string;
  quotes: Array<{
    source_id: string;
    source_symbol: string;
    observed_at: string;
    last_price: number | null;
    close_price: number | null;
    price_change: number | null;
    price_change_percent: number | null;
    volume: number | null;
    value: number | null;
    transaction_count: number | null;
    raw?: Record<string, unknown> | null;
  }>;
}

export type WsMessage = WsSnapshotMessage | WsQuotesMessage;

export interface DescriptiveStats {
  count: number;
  mean: number;
  median: number;
  minimum: number;
  maximum: number;
  std_dev: number;
  coefficient_of_variation: number | null;
  p10: number;
  p25: number;
  p75: number;
  p90: number;
}

export interface Regime {
  observed: Record<string, number>;
  labels: string[];
  interpretation: string;
}

export interface Insight {
  text: string;
  evidence: Record<string, number | string>;
}

export type AnalyticsStatus = "ok" | "insufficient_data";

export interface AnalyticsOverview {
  status: AnalyticsStatus;
  source_id: string;
  source_symbol: string;
  lookback_start: string | null;
  lookback_end: string | null;
  available_points: number;
  min_required_points: number;
  price_stats: DescriptiveStats | null;
  volume_stats: DescriptiveStats | null;
  regime: Regime | null;
  insights: Insight[];
}

export type AnomalySeverity = "low" | "medium" | "high";

export interface Anomaly {
  timestamp: string;
  metric: string;
  source: string;
  method: string;
  observed_value: number;
  expected_range: [number, number] | null;
  severity: AnomalySeverity;
  explanation: string;
}

// ---- market-level forecast / patterns / recommendations (base-load daily VWAP)

/** Markets the forecast/patterns/recommendations can run on (backend MARKETS). */
export const MARKETS = ["free_forward", "free_physical", "power"] as const;
export type Market = (typeof MARKETS)[number];
export const DEFAULT_MARKET: Market = "free_forward";

export interface SeriesInfo {
  market: Market;
  source_id: string;
  symbol: string;
  unit: string;
  first_day: string | null;
  last_day: string | null;
  trading_days: number;
}

export interface ModelScore {
  model: string;
  n: number;
  mae: number;
  mape: number;
  directional_accuracy: number | null;
  by_horizon: Record<string, { n: number; mae: number; mape: number; directional_accuracy: number | null }>;
}

export interface Validation {
  origins: number;
  start: string | null;
  end: string | null;
  /** Default model: lowest validated MAPE (over all horizons). */
  selected_model: string | null;
  scores: ModelScore[];
}

export type Contributions = Partial<Record<"drift" | "season" | "temperature" | "nowruz", number>>;

export interface MonthForecastPoint {
  label: string;
  year: number;
  month: number;
  horizon_months: number;
  price: number;
  low: number;
  high: number;
  t_mean: number;
  t_source: "forecast+normal" | "normal";
  t_normal: number;
  contributions_pct: Contributions;
}

export interface MonthHistoryPoint {
  label: string;
  year: number;
  month: number;
  price: number;
  trading_days: number;
  t_mean: number | null;
}

export interface MonthlyOutlook {
  status: AnalyticsStatus;
  reason: string | null;
  origin_label: string | null;
  origin_price: number | null;
  origin_trading_days: number;
  origin_partial: boolean;
  history: MonthHistoryPoint[];
  points: MonthForecastPoint[];
  /** Every validated model's outlook, keyed by model id. */
  models: Record<string, MonthForecastPoint[]>;
  coefficients: Record<string, number>;
  validation: Validation | null;
  months_used: number;
}

export interface DailyForecastPoint {
  day: string;
  jalali: string;
  horizon_days: number;
  price: number;
  low: number;
  high: number;
  t7: number | null;
  contributions_pct: Contributions;
}

export interface ForecastResponse {
  status: AnalyticsStatus;
  generated_at: string;
  series: SeriesInfo;
  last_day: string | null;
  last_price: number | null;
  interval_pct: number;
  history: { day: string; jalali: string; price: number }[];
  temperature: { day: string; t_mean: number; is_forecast: boolean }[];
  monthly: MonthlyOutlook;
  daily: {
    status: AnalyticsStatus;
    reason: string | null;
    points: DailyForecastPoint[];
    models: Record<string, DailyForecastPoint[]>;
    validation: Validation | null;
  };
}

export interface PatternsResponse {
  status: AnalyticsStatus;
  reason: string | null;
  generated_at: string;
  series: SeriesInfo;
  seasonal: { month: number; mean_deviation_pct: number; std_pct: number; years: number; trading_days: number; consistency: number }[];
  seasonal_years: number[];
  transitions: { from_month: number; to_month: number; mean_change_pct: number; median_change_pct: number; share_up: number; years: number }[];
  weekday: { weekday: number; mean_change_pct: number; share_up: number; n: number }[];
  weekday_since: string | null;
  temperature_bins: { low: number; high: number; mean_deviation_pct: number; n: number }[];
  temperature_correlation: number | null;
  temperature_points: number;
  current_day: string | null;
  current_features: Record<string, number>;
  analogues: {
    day: string;
    jalali: string;
    similarity: number;
    price: number;
    features: Record<string, number>;
    outcomes_pct: Record<string, number>;
  }[];
  analogue_summary: Record<string, number | null>;
}

export type Signal = "upward_pressure" | "downward_pressure" | "mixed";

export interface Evidence {
  key: "outlook_next_month" | "outlook_3_months" | "seasonal_transition" | "analogues_20d" | "short_term";
  kind: "observed" | "model";
  direction: -1 | 0 | 1;
  strength: number;
  value: number | null;
  threshold: number | null;
  detail: Record<string, number | string | null>;
}

export interface RecommendationResponse {
  status: AnalyticsStatus;
  reason: string | null;
  generated_at: string;
  series: SeriesInfo;
  as_of: string | null;
  horizon: string;
  signal: Signal | null;
  score: number | null;
  agreement_pct: number | null;
  volatility_percentile: number | null;
  caution: ("high_volatility" | "temperature_from_normals" | "current_month_partial" | "nowruz_reset_ahead" | "short_history")[];
  evidence: Evidence[];
}

export interface AnomaliesResponse {
  status: AnalyticsStatus;
  source_id: string;
  source_symbol: string;
  available_points: number;
  min_required_points: number;
  anomalies: Anomaly[];
}
