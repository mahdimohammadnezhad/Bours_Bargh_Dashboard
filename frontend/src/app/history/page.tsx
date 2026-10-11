"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { PriceChart } from "@/components/PriceChart";
import { api } from "@/lib/api";
import { formatClockTime, formatCompact, formatPrice } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { PriceHistory } from "@/lib/types";
import { useMarketSocket } from "@/lib/useMarketSocket";

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function downloadCsv(filename: string, history: PriceHistory) {
  const header = "observed_at,last_price,volume\n";
  const rows = history.points
    .map((p) => `${p.observed_at},${p.last_price ?? ""},${p.volume ?? ""}`)
    .join("\n");
  const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function HistoryPage() {
  return (
    <Suspense fallback={null}>
      <HistoryPageInner />
    </Suspense>
  );
}

function HistoryPageInner() {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const { quotes } = useMarketSocket();
  const quoteList = useMemo(() => Array.from(quotes.values()), [quotes]);

  const sources = useMemo(() => Array.from(new Set(quoteList.map((q) => q.source_id))).sort(), [quoteList]);
  // A contract row elsewhere (e.g. the Free Power Market page) can deep-link
  // here with ?source=&symbol= to jump straight to that instrument's history.
  const [sourceOverride, setSourceOverride] = useState<string | null>(() => searchParams.get("source"));
  const sourceId = sourceOverride && sources.includes(sourceOverride) ? sourceOverride : (sources[0] ?? "");

  const symbolsForSource = useMemo(
    () => quoteList.filter((q) => q.source_id === sourceId).map((q) => q.source_symbol).sort(),
    [quoteList, sourceId],
  );
  const [symbolOverride, setSymbolOverride] = useState<string | null>(() => searchParams.get("symbol"));
  const symbol = symbolOverride && symbolsForSource.includes(symbolOverride) ? symbolOverride : (symbolsForSource[0] ?? "");

  const today = useMemo(() => new Date(), []);
  const weekAgo = useMemo(() => new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000), [today]);
  const [from, setFrom] = useState(() => isoDate(weekAgo));
  const [to, setTo] = useState(() => isoDate(today));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-text-primary">{t("history.title")}</h1>
        <p className="text-sm text-text-muted">{t("history.subtitle")}</p>
      </div>

      <section className="flex flex-wrap items-end gap-3 rounded-lg border border-border-hairline bg-surface-1 p-4">
        <label className="flex flex-col gap-1 text-xs text-text-muted">
          {t("history.source")}
          <select
            value={sourceId}
            onChange={(e) => {
              setSourceOverride(e.target.value);
              setSymbolOverride(null);
            }}
            className="ltr-content rounded-md border border-border-hairline bg-surface-0 px-2.5 py-1.5 text-sm text-text-primary"
          >
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-text-muted">
          {t("history.instrument")}
          <select
            value={symbol}
            onChange={(e) => setSymbolOverride(e.target.value)}
            className="ltr-content max-w-[280px] rounded-md border border-border-hairline bg-surface-0 px-2.5 py-1.5 text-sm text-text-primary"
          >
            {symbolsForSource.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-text-muted">
          {t("history.from")}
          <input
            type="date"
            value={from}
            max={to}
            onChange={(e) => setFrom(e.target.value)}
            className="ltr-content rounded-md border border-border-hairline bg-surface-0 px-2.5 py-1.5 text-sm text-text-primary"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-text-muted">
          {t("history.to")}
          <input
            type="date"
            value={to}
            min={from}
            max={isoDate(today)}
            onChange={(e) => setTo(e.target.value)}
            className="ltr-content rounded-md border border-border-hairline bg-surface-0 px-2.5 py-1.5 text-sm text-text-primary"
          />
        </label>
      </section>

      {!sourceId || !symbol ? (
        <EmptyState title={t("history.noInstrument.title")} detail={t("history.noInstrument.detail")} />
      ) : (
        <HistoryResults key={`${sourceId}:${symbol}:${from}:${to}`} sourceId={sourceId} symbol={symbol} from={from} to={to} />
      )}
    </div>
  );
}

function HistoryResults({ sourceId, symbol, from, to }: { sourceId: string; symbol: string; from: string; to: string }) {
  const { t } = useI18n();
  const [history, setHistory] = useState<PriceHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const start = new Date(`${from}T00:00:00Z`).toISOString();
    const end = new Date(`${to}T23:59:59Z`).toISOString();
    api
      .priceHistory(sourceId, symbol, start, end)
      .then((h) => !cancelled && setHistory(h))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [sourceId, symbol, from, to]);

  if (error) return <EmptyState title={t("history.failed")} detail={error} />;
  if (!history) return <EmptyState title={t("history.loading")} />;
  if (history.points.length === 0) {
    return <EmptyState title={t("history.empty.title")} detail={t("history.empty.detail")} />;
  }

  return (
    <>
      <section className="rounded-lg border border-border-hairline bg-surface-1 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="ltr-content text-sm font-semibold text-text-primary">
            {sourceId} · {symbol}
          </h2>
          <div className="flex items-center gap-3">
            <span className="text-xs text-text-muted">{t("history.pointCount", { n: history.points.length })}</span>
            <button
              type="button"
              onClick={() => downloadCsv(`${sourceId}_${symbol}_${from}_${to}.csv`, history)}
              className="rounded-md border border-border-hairline bg-surface-0 px-2.5 py-1 text-xs font-medium text-text-primary transition-colors hover:bg-surface-2"
            >
              {t("history.export")}
            </button>
          </div>
        </div>
        <PriceChart points={history.points} seriesLabel={symbol} />
      </section>

      <section className="overflow-x-auto rounded-lg border border-border-hairline">
        <table className="w-full min-w-[420px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border-hairline bg-surface-1 text-start text-xs text-text-muted">
              <th className="px-3 py-2 text-start font-medium">{t("history.col.time")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("history.col.price")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("history.col.volume")}</th>
            </tr>
          </thead>
          <tbody>
            {history.points
              .slice()
              .reverse()
              .slice(0, 200)
              .map((p, i) => (
                <tr key={i} className="border-b border-border-hairline last:border-0">
                  <td className="px-3 py-2 tabular-nums text-text-muted">{formatClockTime(p.observed_at)}</td>
                  <td className="px-3 py-2 text-end tabular-nums text-text-primary">{formatPrice(p.last_price)}</td>
                  <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{formatCompact(p.volume)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
