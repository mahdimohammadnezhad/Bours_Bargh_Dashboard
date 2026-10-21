"use client";

import Link from "next/link";
import { useMemo } from "react";
import { EmptyState } from "@/components/EmptyState";
import { StatTile } from "@/components/StatTile";
import { formatCompact, formatCompactPrecise, formatInt, formatPrice } from "@/lib/format";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import type { LiveQuote } from "@/lib/useMarketSocket";
import { useMarketSocket } from "@/lib/useMarketSocket";

const SOURCE_ID = "tsetmc";
const LEVELS = [1, 2, 3, 4];

function contractLabel(quote: LiveQuote | undefined): string {
  if (!quote) return "—";
  const raw = quote.raw as { title?: string } | null | undefined;
  return raw?.title || quote.source_symbol;
}

function energySymbolOf(quote: LiveQuote | undefined): string | null {
  const raw = quote?.raw as { powerInstrumentDate?: { energySymbol?: string } } | null | undefined;
  return raw?.powerInstrumentDate?.energySymbol ?? null;
}

function BestLimitsTable({
  title,
  quotes,
  side,
}: {
  title: string;
  quotes: Map<string, LiveQuote>;
  side: "DEMAND" | "SUPPLY";
}) {
  const { t } = useI18n();
  // Levels the book no longer has come through as empty rows (no price).
  const rows = LEVELS.map((level) => quotes.get(`${SOURCE_ID}:TSETMC_FREE_${side}_L${level}`)).filter(
    (q): q is LiveQuote => q !== undefined && q.last_price != null,
  );

  return (
    <section className="rounded-lg border border-border-hairline">
      <h2
        className={`px-4 py-2.5 text-sm font-semibold ${
          side === "DEMAND" ? "bg-[var(--status-good)]/10 text-[var(--status-good)]" : "bg-[var(--status-critical)]/10 text-[var(--status-critical)]"
        }`}
      >
        {title}
      </h2>
      {rows.length === 0 ? (
        <div className="p-4">
          <EmptyState title={t("freePower.empty.title")} detail={t("freePower.empty.detail")} />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-hairline bg-surface-1 text-start text-xs text-text-muted">
                <th className="px-3 py-2 text-start font-medium">{t("freePower.col.contract")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("freePower.col.price")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("freePower.col.volume")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("freePower.col.value")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("freePower.col.count")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const symbol = energySymbolOf(row);
                const label = contractLabel(row);
                const cell = symbol ? (
                  <Link
                    href={`/history?source=${SOURCE_ID}&symbol=${encodeURIComponent(symbol)}`}
                    className="ltr-content text-[var(--series-1)] hover:underline"
                    title={t("freePower.viewHistory")}
                  >
                    {label}
                  </Link>
                ) : (
                  <span className="ltr-content">{label}</span>
                );
                return (
                  <tr key={row.source_symbol} className="border-b border-border-hairline last:border-0">
                    <td className="px-3 py-2 font-medium text-text-primary">{cell}</td>
                    <td className="px-3 py-2 text-end tabular-nums text-text-primary">{formatPrice(row.last_price)}</td>
                    <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{formatCompact(row.volume)}</td>
                    <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{formatCompact(row.value)}</td>
                    <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{formatInt(row.transaction_count)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function FreePowerMarketPage() {
  const { t } = useI18n();
  const { quotes } = useMarketSocket();

  const overview = quotes.get(`${SOURCE_ID}:TSETMC_FREE_POWER_OVERVIEW`);
  const overviewRaw = useMemo(
    () =>
      (overview?.raw as {
        marketStateTitle?: string;
        totalValue?: number;
        totalCount?: number;
        mazadValue?: number;
        mazadCount?: number;
        f60_MarketActivityQTotCap?: number;
        f60_MarketActivityZTotTran?: number;
        dggPlus60_MarketActivityQTotCap?: number;
      } | null) ?? null,
    [overview],
  );
  // Same rows, order and wording as tsetmc.ir's "بازار برق آزاد در یک نگاه".
  const glance: { label: TranslationKey; value: string }[] = overviewRaw
    ? [
        { label: "freePower.marketStatus", value: overviewRaw.marketStateTitle ?? "—" },
        { label: "freePower.physicalValue", value: formatCompactPrecise(overviewRaw.totalValue ?? null) },
        { label: "freePower.totalCount", value: formatInt(overviewRaw.totalCount ?? null) },
        { label: "freePower.mazadValue", value: formatCompactPrecise(overviewRaw.mazadValue ?? null) },
        { label: "freePower.mazadCount", value: formatInt(overviewRaw.mazadCount ?? null) },
        { label: "freePower.forwardValue", value: formatCompactPrecise(overviewRaw.f60_MarketActivityQTotCap ?? null) },
        { label: "freePower.forwardCount", value: formatInt(overviewRaw.f60_MarketActivityZTotTran ?? null) },
        { label: "freePower.totalValue", value: formatCompactPrecise(overviewRaw.dggPlus60_MarketActivityQTotCap ?? null) },
      ]
    : [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-text-primary">{t("freePower.title")}</h1>
        <p className="text-sm text-text-muted">{t("freePower.subtitle")}</p>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("freePower.atGlance")}</h2>
        {!overview ? (
          <EmptyState title={t("freePower.empty.title")} detail={t("freePower.empty.detail")} />
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {glance.map((g) => (
              <StatTile key={g.label} label={t(g.label)} value={g.value} />
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <BestLimitsTable title={t("freePower.topDemand")} quotes={quotes} side="DEMAND" />
        <BestLimitsTable title={t("freePower.topSupply")} quotes={quotes} side="SUPPLY" />
      </div>
    </div>
  );
}
