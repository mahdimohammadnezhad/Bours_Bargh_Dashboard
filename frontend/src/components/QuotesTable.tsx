"use client";

import { useMemo, useState } from "react";

import { formatCompact, formatClockTime, formatPercent, formatPrice } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { quoteDisplayName, type LiveQuote } from "@/lib/useMarketSocket";
import { EmptyState } from "./EmptyState";

const DEFAULT_ROW_LIMIT = 50;

export function QuotesTable({ quotes, selected, onSelect }: { quotes: LiveQuote[]; selected: string | null; onSelect: (key: string) => void }) {
  const [showAll, setShowAll] = useState(false);
  const { t } = useI18n();

  // With a real per-instrument source wired in (e.g. IEE's derivative power
  // trade board, ~450 contracts per cycle), rendering every row by default
  // produced a single-column table tens of thousands of pixels tall - not
  // usable as an "overview". Cap it and let the user opt into the full list.
  const visibleQuotes = useMemo(
    () => (showAll ? quotes : quotes.slice(0, DEFAULT_ROW_LIMIT)),
    [quotes, showAll]
  );

  if (quotes.length === 0) {
    return <EmptyState title={t("quotes.empty.title")} detail={t("quotes.empty.detail")} />;
  }

  return (
    <div className="rounded-lg border border-border-hairline">
      <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border-hairline bg-surface-1 text-start text-xs text-text-muted">
            <th className="px-3 py-2 text-start font-medium">{t("quotes.col.source")}</th>
            <th className="px-3 py-2 text-start font-medium">{t("quotes.col.symbol")}</th>
            <th className="px-3 py-2 text-end font-medium">{t("quotes.col.lastPrice")}</th>
            <th className="px-3 py-2 text-end font-medium">{t("quotes.col.changePercent")}</th>
            <th className="px-3 py-2 text-end font-medium">{t("quotes.col.volume")}</th>
            <th className="px-3 py-2 text-end font-medium">{t("quotes.col.updated")}</th>
          </tr>
        </thead>
        <tbody>
          {visibleQuotes.map((q) => {
            const key = `${q.source_id}:${q.source_symbol}`;
            const name = quoteDisplayName(q);
            const change = q.price_change_percent;
            const deltaColor =
              change === null || change === undefined || change === 0
                ? "text-text-muted"
                : change > 0
                  ? "text-[var(--delta-up-good)]"
                  : "text-[var(--delta-down-bad)]";
            return (
              <tr
                key={key}
                onClick={() => onSelect(key)}
                className={`cursor-pointer border-b border-border-hairline last:border-0 hover:bg-surface-1 ${
                  selected === key ? "bg-surface-1" : ""
                }`}
              >
                <td className="ltr-content px-3 py-2 text-start text-text-secondary">{q.source_id}</td>
                <td className="px-3 py-2 text-start">
                  {name && <div className="font-medium text-text-primary">{name}</div>}
                  <div className={`ltr-content ${name ? "text-xs text-text-muted" : "font-medium text-text-primary"}`}>
                    {q.source_symbol}
                  </div>
                </td>
                <td className="px-3 py-2 text-end tabular-nums text-text-primary">{formatPrice(q.last_price)}</td>
                <td className={`px-3 py-2 text-end tabular-nums font-medium ${deltaColor}`}>{formatPercent(change)}</td>
                <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{formatCompact(q.volume)}</td>
                <td className="px-3 py-2 text-end tabular-nums text-text-muted">{formatClockTime(q.observed_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      {quotes.length > DEFAULT_ROW_LIMIT && (
        <div className="flex items-center justify-between border-t border-border-hairline bg-surface-1 px-3 py-2 text-xs text-text-muted">
          <span>
            {showAll
              ? t("quotes.showAll", { total: quotes.length })
              : t("quotes.showingOf", { shown: visibleQuotes.length, total: quotes.length })}
          </span>
          <button
            type="button"
            onClick={() => setShowAll((prev) => !prev)}
            className="font-medium text-text-primary hover:underline"
          >
            {showAll ? t("quotes.showFewer") : t("quotes.showAll", { total: quotes.length })}
          </button>
        </div>
      )}
    </div>
  );
}
