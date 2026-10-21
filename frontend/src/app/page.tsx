"use client";

import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ForecastSummaryCard } from "@/components/ForecastSummaryCard";
import { PriceChart } from "@/components/PriceChart";
import { QuotesTable } from "@/components/QuotesTable";
import { SourceHealthPanel } from "@/components/SourceHealthPanel";
import { StatTile } from "@/components/StatTile";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import { formatCompact, formatInt, formatPercent, formatPrice, formatRelativeTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { MarketStatus, PriceHistory } from "@/lib/types";
import { quoteDisplayName, useMarketSocket, type LiveQuote } from "@/lib/useMarketSocket";

export default function OverviewPage() {
  const { t } = useI18n();
  const { connectionState, quotes, lastMessageAt } = useMarketSocket();
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [history, setHistory] = useState<PriceHistory | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api
        .marketStatus()
        .then((s) => !cancelled && setMarketStatus(s))
        .catch(() => undefined);
    };
    load();
    const id = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Most recently changed first (the backend only pushes changes, so this
  // reads as a live ticker), then by traded value - otherwise ~440 mostly
  // idle IEE contracts and long-expired ones fill the visible rows in
  // arbitrary order.
  const quoteList = useMemo(
    () =>
      Array.from(quotes.values())
        // Order-book levels the book no longer has (explicit empty rows).
        .filter((q) => !(q.raw as { empty?: boolean } | null | undefined)?.empty)
        .sort(
        (a, b) =>
          new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime() ||
          (b.value ?? -1) - (a.value ?? -1),
      ),
    [quotes],
  );

  // The dashboard is about Free Power: open on IEE's Free market daily
  // average (matches tsetmc.ir's physical Free Power total). Picking the
  // most-traded instrument instead landed on the main regulated market
  // (~4,900 Rials/kWh vs Free Power's ~100,000+), which read as a wrong price.
  // Falls back to today's most-traded priced instrument, then any priced quote.
  const defaultQuote = useMemo(() => {
    const free = quoteList.find((q) => q.source_id === "iee_new" && q.source_symbol === "IEE_FREE_DAY" && q.last_price != null);
    if (free) return free;
    const today = new Date().toDateString();
    const tradedToday = quoteList.filter(
      (q) =>
        q.last_price != null &&
        (q.transaction_count ?? 0) > 0 &&
        new Date(q.observed_at).toDateString() === today,
    );
    const mostTraded = tradedToday.reduce<LiveQuote | null>(
      (best, q) => (best === null || (q.value ?? 0) > (best.value ?? 0) ? q : best),
      null,
    );
    return mostTraded ?? quoteList.find((q) => q.last_price != null) ?? quoteList[0] ?? null;
  }, [quoteList]);

  const effectiveSelectedKey =
    selectedKey && quotes.has(selectedKey)
      ? selectedKey
      : defaultQuote
        ? `${defaultQuote.source_id}:${defaultQuote.source_symbol}`
        : null;

  const selectedQuote = effectiveSelectedKey ? quotes.get(effectiveSelectedKey) : null;

  useEffect(() => {
    if (!selectedQuote) return;
    let cancelled = false;
    api
      .priceHistory(selectedQuote.source_id, selectedQuote.source_symbol)
      .then((h) => !cancelled && setHistory(h))
      .catch(() => !cancelled && setHistory(null));
    return () => {
      cancelled = true;
    };
    // Only re-fetch when the selected instrument changes, not on every price tick.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedQuote?.source_id, selectedQuote?.source_symbol]);

  const degradedSources = (marketStatus?.sources ?? []).filter(
    (s) => s.status === "degraded" || s.status === "down",
  );

  const connectionLabel =
    connectionState === "open" ? t("conn.live") : connectionState === "connecting" ? t("conn.connecting") : t("conn.disconnected");
  const connectionColor =
    connectionState === "open"
      ? "text-[var(--status-good)]"
      : connectionState === "connecting"
        ? "text-[var(--status-warning)]"
        : "text-[var(--status-critical)]";

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-hairline bg-surface-1 px-4 py-3">
        <div className="flex items-center gap-3 text-sm">
          <span className={`font-medium ${connectionColor}`}>● {connectionLabel}</span>
          <span className="text-text-muted">
            {marketStatus?.is_active_session ? t("session.active") : t("session.inactive")}
          </span>
          <span className="text-text-muted">
            {t("lastUpdate")} {formatRelativeTime(lastMessageAt ? new Date(lastMessageAt).toISOString() : null, now, t)}
          </span>
        </div>
        <div className="flex gap-2">
          {(marketStatus?.sources ?? []).map((s) => (
            <StatusPill key={s.source_id} status={s.status} />
          ))}
        </div>
      </section>

      {degradedSources.length > 0 && (
        <section className="rounded-lg border border-[var(--status-warning)]/40 bg-[var(--status-warning)]/10 px-4 py-3 text-sm">
          <p className="font-medium text-text-primary">{t("alerts.title")}</p>
          <ul className="mt-1 list-inside list-disc text-text-secondary">
            {degradedSources.map((s) => (
              <li key={s.source_id}>
                <span className="ltr-content">{s.name}</span> {t("alerts.is")}{" "}
                <strong className="ltr-content">{s.status}</strong>
                {s.last_error ? <span className="ltr-content"> — {s.last_error}</span> : ""}
              </li>
            ))}
          </ul>
        </section>
      )}

      <ForecastSummaryCard />

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label={t("kpi.currentPrice")} value={formatPrice(selectedQuote?.last_price)} />
        <StatTile
          label={t("kpi.change")}
          value={formatPercent(selectedQuote?.price_change_percent)}
          deltaDirection={
            !selectedQuote?.price_change_percent
              ? "flat"
              : selectedQuote.price_change_percent > 0
                ? "up"
                : "down"
          }
        />
        <StatTile label={t("kpi.volume")} value={formatCompact(selectedQuote?.volume)} />
        <StatTile label={t("kpi.tradedValue")} value={formatCompact(selectedQuote?.value)} />
        <StatTile label={t("kpi.transactions")} value={formatInt(selectedQuote?.transaction_count)} />
        <StatTile label={t("kpi.instrumentsTracked")} value={String(quoteList.length)} />
      </section>

      <section className="rounded-lg border border-border-hairline bg-surface-1 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="ltr-content text-sm font-semibold text-text-primary">
            {selectedQuote
              ? [quoteDisplayName(selectedQuote), selectedQuote.source_id, selectedQuote.source_symbol].filter(Boolean).join(" · ")
              : t("chart.defaultTitle")}
          </h2>
          <span className="text-xs text-text-muted">{t("chart.last7days")}</span>
        </div>
        {history && history.points.length >= 2 ? (
          <PriceChart points={history.points} seriesLabel={selectedQuote?.source_symbol ?? "price"} />
        ) : (
          <EmptyState title={t("chart.noData.title")} detail={t("chart.noData.detail")} />
        )}
      </section>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="min-w-0 lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("quotes.title")}</h2>
          <QuotesTable quotes={quoteList} selected={effectiveSelectedKey} onSelect={setSelectedKey} />
        </div>
        <div className="min-w-0">
          <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("sourceHealth.title")}</h2>
          <SourceHealthPanel sources={marketStatus?.sources ?? []} />
        </div>
      </section>
    </div>
  );
}
