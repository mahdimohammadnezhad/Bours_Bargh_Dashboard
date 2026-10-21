"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { StatTile } from "@/components/StatTile";
import { ForecastTab } from "@/components/analytics/ForecastTab";
import { PatternsTab } from "@/components/analytics/PatternsTab";
import { RecommendationsTab } from "@/components/analytics/RecommendationsTab";
import { api } from "@/lib/api";
import { formatPercent, formatPrice } from "@/lib/format";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import { DEFAULT_MARKET, MARKETS, type Market } from "@/lib/types";
import type { AnalyticsOverview, Anomaly, AnomaliesResponse, AnomalySeverity } from "@/lib/types";
import { useMarketSocket } from "@/lib/useMarketSocket";

const TAB_KEYS = ["overview", "anomalies", "forecast", "patterns", "recommendations"] as const;
type TabKey = (typeof TAB_KEYS)[number];
const TAB_LABEL_KEY: Record<TabKey, TranslationKey> = {
  overview: "analytics.tab.overview",
  anomalies: "analytics.tab.anomalies",
  forecast: "analytics.tab.forecast",
  patterns: "analytics.tab.patterns",
  recommendations: "analytics.tab.recommendations",
};
// These work on the whole power market's daily series, not the picked instrument.
const MARKET_TABS: TabKey[] = ["forecast", "patterns", "recommendations"];

const SEVERITY_COLOR: Record<AnomalySeverity, string> = {
  low: "var(--status-neutral)",
  medium: "var(--status-warning)",
  high: "var(--status-critical)",
};

function formatStat(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export default function AnalyticsPage() {
  return (
    <Suspense fallback={null}>
      <AnalyticsPageInner />
    </Suspense>
  );
}

function AnalyticsPageInner() {
  const { t } = useI18n();
  const { quotes } = useMarketSocket();
  // ?tab=forecast lets other pages (the overview's forecast card) deep-link.
  const searchParams = useSearchParams();
  const [active, setActive] = useState<TabKey>(() => {
    const requested = searchParams.get("tab");
    return TAB_KEYS.includes(requested as TabKey) ? (requested as TabKey) : "overview";
  });
  const isMarketTab = MARKET_TABS.includes(active);
  // Free Power by default; ?market= lets other pages deep-link.
  const [market, setMarket] = useState<Market>(() => {
    const requested = searchParams.get("market");
    return MARKETS.includes(requested as Market) ? (requested as Market) : DEFAULT_MARKET;
  });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const quoteList = useMemo(() => Array.from(quotes.values()), [quotes]);
  const defaultQuote = useMemo(
    () => quoteList.find((q) => q.last_price !== null && q.last_price !== undefined) ?? quoteList[0] ?? null,
    [quoteList],
  );
  const effectiveKey =
    selectedKey && quotes.has(selectedKey)
      ? selectedKey
      : defaultQuote
        ? `${defaultQuote.source_id}:${defaultQuote.source_symbol}`
        : null;
  const [sourceId, symbol] = effectiveKey ? effectiveKey.split(":") : [null, null];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-text-primary">{t("analytics.title")}</h1>
          <p className="text-sm text-text-muted">{t("analytics.subtitle")}</p>
        </div>
        {!isMarketTab && quoteList.length > 0 && (
          <select
            value={effectiveKey ?? ""}
            onChange={(e) => setSelectedKey(e.target.value)}
            className="ltr-content rounded-md border border-border-hairline bg-surface-1 px-3 py-1.5 text-sm text-text-primary"
          >
            {quoteList.map((q) => {
              const key = `${q.source_id}:${q.source_symbol}`;
              return (
                <option key={key} value={key}>
                  {q.source_id} · {q.source_symbol}
                </option>
              );
            })}
          </select>
        )}
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-border-hairline">
        {TAB_KEYS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActive(tab)}
            className={`rounded-t-md px-3 py-2 text-sm font-medium ${
              active === tab
                ? "border-b-2 border-[var(--series-1)] text-text-primary"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {t(TAB_LABEL_KEY[tab])}
          </button>
        ))}
      </div>

      {isMarketTab && (
        <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t("analytics.market")}>
          <span className="text-xs font-medium text-text-secondary">{t("analytics.market")}</span>
          {MARKETS.map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={market === m}
              onClick={() => setMarket(m)}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                market === m
                  ? "border-[var(--series-1)] bg-[var(--series-1)]/10 font-semibold text-text-primary"
                  : "border-border-hairline text-text-secondary hover:text-text-primary"
              }`}
            >
              {t(`market.${m}` as TranslationKey)}
            </button>
          ))}
        </div>
      )}

      {/* key={market}: each market is a fresh load, not a stale mix. */}
      {active === "forecast" ? (
        <ForecastTab key={market} market={market} />
      ) : active === "patterns" ? (
        <PatternsTab key={market} market={market} />
      ) : active === "recommendations" ? (
        <RecommendationsTab key={market} market={market} />
      ) : !sourceId || !symbol ? (
        <EmptyState title={t("analytics.noInstrument.title")} detail={t("analytics.noInstrument.detail")} />
      ) : active === "overview" ? (
        <OverviewTab key={effectiveKey} sourceId={sourceId} symbol={symbol} />
      ) : (
        <AnomaliesTab key={effectiveKey} sourceId={sourceId} symbol={symbol} />
      )}
    </div>
  );
}

function InsufficientData({ available, required }: { available: number; required: number }) {
  const { t } = useI18n();
  return (
    <EmptyState
      title={t("analytics.insufficientData.title")}
      detail={t("analytics.insufficientData.detail", { available, required })}
    />
  );
}

function OverviewTab({ sourceId, symbol }: { sourceId: string; symbol: string }) {
  const { t } = useI18n();
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .analyticsOverview(sourceId, symbol)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [sourceId, symbol]);

  if (error) return <EmptyState title={t("analytics.failedOverview")} detail={error} />;
  if (!data) return <EmptyState title={t("analytics.loading")} />;
  if (data.status === "insufficient_data") {
    return <InsufficientData available={data.available_points} required={data.min_required_points} />;
  }

  const { price_stats, volume_stats, regime, insights } = data;

  return (
    <div className="flex flex-col gap-6">
      {price_stats && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("analytics.priceStats", { n: data.available_points })}</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile label={t("analytics.stat.mean")} value={formatStat(price_stats.mean)} />
            <StatTile label={t("analytics.stat.median")} value={formatStat(price_stats.median)} />
            <StatTile label={t("analytics.stat.stdDev")} value={formatStat(price_stats.std_dev)} />
            <StatTile
              label={t("analytics.stat.cv")}
              value={price_stats.coefficient_of_variation !== null ? formatPercent(price_stats.coefficient_of_variation * 100) : "—"}
            />
            <StatTile label={t("analytics.stat.p10p90")} value={`${formatStat(price_stats.p10, 1)} / ${formatStat(price_stats.p90, 1)}`} />
            <StatTile label={t("analytics.stat.minMax")} value={`${formatStat(price_stats.minimum, 1)} / ${formatStat(price_stats.maximum, 1)}`} />
          </div>
        </section>
      )}

      {volume_stats && (
        <section>
          <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("analytics.volumeStats")}</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile label={t("analytics.stat.mean")} value={formatPrice(volume_stats.mean)} />
            <StatTile label={t("analytics.stat.median")} value={formatPrice(volume_stats.median)} />
            <StatTile label={t("analytics.stat.stdDev")} value={formatPrice(volume_stats.std_dev)} />
            <StatTile label={t("analytics.stat.p10p90")} value={`${formatPrice(volume_stats.p10)} / ${formatPrice(volume_stats.p90)}`} />
          </div>
        </section>
      )}

      {regime && (
        <section className="rounded-lg border border-border-hairline bg-surface-1 p-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-text-primary">{t("analytics.regime")}</h2>
            {regime.labels.map((label) => (
              <span
                key={label}
                className="ltr-content rounded-full border border-border-hairline px-2 py-0.5 text-xs font-medium text-text-secondary"
              >
                {label}
              </span>
            ))}
          </div>
          <p className="text-sm text-text-secondary">{regime.interpretation}</p>
          <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Object.entries(regime.observed).map(([key, value]) => (
              <div key={key}>
                <dt className="ltr-content text-xs text-text-muted">{key.replace(/_/g, " ")}</dt>
                <dd className="text-sm font-medium text-text-primary">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-text-muted">{t("analytics.regime.disclaimer")}</p>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("analytics.insights")}</h2>
        {insights.length === 0 ? (
          <EmptyState title={t("analytics.insights.empty.title")} detail={t("analytics.insights.empty.detail")} />
        ) : (
          <ul className="flex flex-col gap-2">
            {insights.map((insight, i) => (
              <li key={i} className="rounded-lg border border-border-hairline bg-surface-1 p-3">
                <p className="text-sm text-text-primary">{insight.text}</p>
                <p className="mt-1 text-xs text-text-muted">
                  {t("analytics.insights.why")}{" "}
                  <span className="ltr-content">
                    {Object.entries(insight.evidence)
                      .map(([k, v]) => `${k.replace(/_/g, " ")}=${v}`)
                      .join(", ")}
                  </span>
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function AnomaliesTab({ sourceId, symbol }: { sourceId: string; symbol: string }) {
  const { t } = useI18n();
  const [data, setData] = useState<AnomaliesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .anomalies(sourceId, symbol)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [sourceId, symbol]);

  if (error) return <EmptyState title={t("analytics.failedAnomalies")} detail={error} />;
  if (!data) return <EmptyState title={t("analytics.loading")} />;
  if (data.status === "insufficient_data") {
    return <InsufficientData available={data.available_points} required={data.min_required_points} />;
  }
  if (data.anomalies.length === 0) {
    return (
      <EmptyState
        title={t("analytics.anomalies.empty.title")}
        detail={t("analytics.anomalies.empty.detail", { n: data.available_points })}
      />
    );
  }

  return (
    <ul className="flex flex-col gap-2">
      {data.anomalies.map((a: Anomaly, i: number) => (
        <li key={i} className="rounded-lg border border-border-hairline bg-surface-1 p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium" style={{ color: SEVERITY_COLOR[a.severity] }}>
              ● {a.severity}
            </span>
            <span className="ltr-content text-text-muted">{new Date(a.timestamp).toLocaleString()}</span>
            <span className="ltr-content rounded-full border border-border-hairline px-2 py-0.5 text-text-secondary">
              {a.metric}
            </span>
            <span className="text-text-muted">
              {t("analytics.anomalies.via")} <span className="ltr-content">{a.method}</span>
            </span>
          </div>
          <p className="mt-1 text-sm text-text-primary">{a.explanation}</p>
          <p className="ltr-content mt-1 text-xs text-text-muted">
            {t("analytics.anomalies.observed")} {formatStat(a.observed_value, 2)}
            {a.expected_range
              ? ` · ${t("analytics.anomalies.expectedRange")} [${formatStat(a.expected_range[0], 2)}, ${formatStat(a.expected_range[1], 2)}]`
              : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}
