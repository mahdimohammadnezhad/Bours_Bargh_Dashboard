"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { isolate, monthLabel, price, signedPct } from "@/components/analytics/common";
import { api } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import type { ForecastResponse, RecommendationResponse } from "@/lib/types";

/** Compact next-month outlook + signal for the overview page. Renders
 * nothing until the backend has enough history to forecast. */
export function ForecastSummaryCard() {
  const { t } = useI18n();
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [rec, setRec] = useState<RecommendationResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.forecast().then((f) => !cancelled && setForecast(f)).catch(() => undefined);
    api.recommendations().then((r) => !cancelled && setRec(r)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const m = forecast?.monthly;
  const next = m?.points[0];
  if (!m || m.status !== "ok" || !next || m.origin_price === null) return null;

  return (
    <section className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border-hairline bg-surface-1 px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <p className="text-xs font-medium text-text-secondary">{t("fc.card.title")}</p>
        <p className="text-sm text-text-muted">{monthLabel(t, next.label)}</p>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-text-primary">{price(next.price)}</span>
        <span className="text-sm text-text-muted">{t("analytics.unit")}</span>
        <span className="text-xs text-text-secondary">{signedPct(100 * (next.price / m.origin_price - 1))}</span>
      </div>
      <p className="text-xs text-text-secondary">{t("fc.range", { low: price(next.low), high: price(next.high) })}</p>
      {rec?.status === "ok" && rec.signal && (
        <p className="text-xs text-text-secondary">
          {t("fc.card.signal")} <span className="font-semibold text-text-primary">{t(`rc.signal.${rec.signal}` as TranslationKey)}</span>
          {rec.agreement_pct !== null && <span className="text-text-muted"> · {isolate(`${Math.round(rec.agreement_pct)}%`)}</span>}
        </p>
      )}
      <Link href="/analytics?tab=forecast" className="text-xs font-medium text-[var(--series-1)] hover:underline">
        {t("fc.card.more")}
      </Link>
    </section>
  );
}
