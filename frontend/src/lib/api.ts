import type {
  AnalyticsOverview,
  AnomaliesResponse,
  CollectorLog,
  ForecastResponse,
  Instrument,
  MarketStatus,
  PatternsResponse,
  PriceHistory,
  Quote,
  RecommendationResponse,
  SourceHealth,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function getJson<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_BASE);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, value);
    }
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${path} failed: HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  marketStatus: () => getJson<MarketStatus>("/api/market/status"),
  sourceHealth: () => getJson<SourceHealth[]>("/api/health/sources"),
  quotes: (sourceId?: string) =>
    getJson<Quote[]>("/api/market/quotes", sourceId ? { source_id: sourceId } : undefined),
  instruments: () => getJson<Instrument[]>("/api/market/instruments"),
  priceHistory: (sourceId: string, symbol: string, start?: string, end?: string) =>
    getJson<PriceHistory>("/api/history/prices", {
      source_id: sourceId,
      symbol,
      ...(start ? { start } : {}),
      ...(end ? { end } : {}),
    }),
  collectorLogs: (sourceId?: string, limit = 50) =>
    getJson<CollectorLog[]>(
      "/api/health/logs",
      sourceId ? { source_id: sourceId, limit: String(limit) } : { limit: String(limit) },
    ),
  analyticsOverview: (sourceId: string, symbol: string, lookbackDays = 30) =>
    getJson<AnalyticsOverview>("/api/analytics/overview", {
      source_id: sourceId,
      symbol,
      lookback_days: String(lookbackDays),
    }),
  anomalies: (sourceId: string, symbol: string, lookbackDays = 30) =>
    getJson<AnomaliesResponse>("/api/analytics/anomalies", {
      source_id: sourceId,
      symbol,
      lookback_days: String(lookbackDays),
    }),
  forecast: () => getJson<ForecastResponse>("/api/analytics/forecast"),
  patterns: () => getJson<PatternsResponse>("/api/analytics/patterns"),
  recommendations: () => getJson<RecommendationResponse>("/api/analytics/recommendations"),
};

export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/market";
