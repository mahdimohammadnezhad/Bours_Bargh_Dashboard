"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { isolate, monthLabel, price, signedPct } from "@/components/analytics/common";
import { api } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import type { ForecastResponse, RecommendationResponse } from "@/lib/types";

/** Free Power at a glance for the overview page: the latest forward
 * base-load trade, and the next month (when a validated monthly outlook
 * exists) or the next two weeks' range. Renders nothing until there is data. */
export function ForecastSummaryCard() {
  const { t } = useI18n();
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [rec, setRec] = useState<RecommendationResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.forecast("free_forward").then((f) => !cancelled && setForecast(f)).catch(() => undefined);
    api.recommendations("free_forward").then((r) => !cancelled && setRec(r)).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!forecast || forecast.last_price === null) return null;
  const lastJalali = forecast.history[forecast.history.length - 1]?.jalali;
  const nextMonth = forecast.monthly.status === "ok" ? forecast.monthly.points[0] : undefined;
  const shortEnd = forecast.daily.status === "ok" ? forecast.daily.points[forecast.daily.points.length - 1] : undefined;

  return (
    <section className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border-hairline bg-surface-1 px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <p className="text-xs font-medium text-text-secondary">{t("fc.card.titleFree")}</p>
        <p className="text-sm text-text-muted">
          {t("fc.card.lastTrade")} <span className="tabular-nums">{lastJalali}</span>
        </p>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-text-primary">{price(forecast.last_price)}</span>
        <span className="text-sm text-text-muted">{t("analytics.unit")}</span>
      </div>
      {nextMonth && forecast.monthly.origin_price !== null ? (
        <p className="text-xs text-text-secondary">
          {t("fc.forecastFor", { month: monthLabel(t, nextMonth.label) })}: {price(nextMonth.price)}{" "}
          {signedPct(100 * (nextMonth.price / forecast.monthly.origin_price - 1))}
        </p>
      ) : (
        shortEnd && (
          <p className="text-xs text-text-secondary">{t("fc.card.range14", { low: price(shortEnd.low), high: price(shortEnd.high) })}</p>
        )
      )}
      {rec?.status === "ok" && rec.signal && (
        <p className="text-xs text-text-secondary">
          {t("fc.card.signal")} <span className="font-semibold text-text-primary">{t(`rc.signal.${rec.signal}` as TranslationKey)}</span>
          {rec.agreement_pct !== null && <span className="text-text-muted"> · {isolate(`${Math.round(rec.agreement_pct)}%`)}</span>}
        </p>
      )}
      <Link href="/analytics?tab=forecast&market=free_forward" className="text-xs font-medium text-[var(--series-1)] hover:underline">
        {t("fc.card.more")}
      </Link>
    </section>
  );
}
