"use client";

import { EmptyState } from "@/components/EmptyState";
import { api } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import type { Evidence, Signal } from "@/lib/types";
import { MarketScope, SectionCard, isolate, monthLabel, monthName, signedPct, useEndpoint } from "./common";

type Translate = ReturnType<typeof useI18n>["t"];

const SIGNAL_ICON: Record<Signal, string> = { upward_pressure: "↑", downward_pressure: "↓", mixed: "↔" };
const DIRECTION_ICON: Record<number, string> = { 1: "↑", [-1]: "↓", 0: "·" };

function evidenceText(t: Translate, e: Evidence): string {
  const d = e.detail;
  switch (e.key) {
    case "outlook_next_month":
    case "outlook_3_months":
      return t(`rc.ev.${e.key}`, { month: monthLabel(t, String(d.month)), value: signedPct(e.value) });
    case "seasonal_transition":
      return t("rc.ev.seasonal_transition", {
        from: monthName(t, Number(d.from_month)),
        to: monthName(t, Number(d.to_month)),
        value: signedPct(e.value),
        up: Number(d.years_up),
        years: Number(d.years),
      });
    case "analogues_20d":
      return t("rc.ev.analogues_20d", {
        value: isolate(`${Math.round(e.value ?? 0)}%`),
        median: signedPct(typeof d.median_change_pct === "number" ? d.median_change_pct : null),
      });
    case "short_term":
      return d.model === "naive"
        ? t("rc.ev.short_term.naive")
        : t("rc.ev.short_term", { value: signedPct(e.value), model: t(`fc.model.${d.model}` as TranslationKey) });
  }
}

export function RecommendationsTab() {
  const { t } = useI18n();
  const { data, error } = useEndpoint(api.recommendations);

  if (error) return <EmptyState title={t("rc.failed")} detail={error} />;
  if (!data) return <EmptyState title={t("analytics.loading")} />;
  if (data.status !== "ok" || !data.signal) {
    return <EmptyState title={t("rc.failed")} detail={t("fc.insufficient", { reason: data.reason ?? "—" })} />;
  }
  const signal = data.signal;

  return (
    <div className="flex flex-col gap-6">
      <MarketScope series={data.series} />

      <section className="flex flex-wrap items-center gap-4 rounded-lg border border-border-hairline bg-surface-1 p-5">
        <span
          className="flex h-14 w-14 items-center justify-center rounded-full border border-border-hairline text-3xl text-text-primary"
          aria-hidden
        >
          {SIGNAL_ICON[signal]}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-2xl font-semibold text-text-primary">{t(`rc.signal.${signal}` as TranslationKey)}</p>
          <p className="text-xs text-text-muted">{t("rc.horizon", { asOf: data.as_of ?? "—" })}</p>
        </div>
        {data.agreement_pct !== null && (
          <div className="flex flex-col items-end gap-1 text-end">
            <p className="text-sm font-semibold text-text-primary">{t("rc.agreement", { pct: isolate(`${Math.round(data.agreement_pct)}%`) })}</p>
            <p className="max-w-xs text-[11px] text-text-muted">{t("rc.agreement.note")}</p>
          </div>
        )}
      </section>

      {data.caution.length > 0 && (
        <section className="rounded-lg border border-[var(--status-warning)]/40 bg-[var(--status-warning)]/10 px-4 py-3">
          <p className="text-sm font-medium text-text-primary">⚠ {t("rc.caution.title")}</p>
          <ul className="mt-1 list-inside list-disc text-xs text-text-secondary">
            {data.caution.map((c) => (
              <li key={c}>{t(`rc.caution.${c}` as TranslationKey)}</li>
            ))}
          </ul>
        </section>
      )}

      <SectionCard title={t("rc.why")} note={t("rc.strength.note")}>
        <ul className="flex flex-col gap-2">
          {data.evidence.map((e) => (
            <li key={e.key} className="flex flex-wrap items-center gap-3 rounded-md border border-border-hairline bg-surface-0 px-3 py-2.5">
              <span
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border-hairline text-sm text-text-primary"
                title={t(e.direction > 0 ? "rc.dir.up" : e.direction < 0 ? "rc.dir.down" : "rc.dir.none")}
              >
                {DIRECTION_ICON[e.direction]}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <p className="text-sm text-text-primary">{evidenceText(t, e)}</p>
                <p className="text-[11px] text-text-muted">
                  {t(e.direction > 0 ? "rc.dir.up" : e.direction < 0 ? "rc.dir.down" : "rc.dir.none")}
                </p>
              </div>
              <span className="rounded-full border border-border-hairline px-2 py-0.5 text-[11px] text-text-secondary">
                {t(`rc.kind.${e.kind}` as TranslationKey)}
              </span>
              <div className="flex w-28 flex-col gap-1">
                <div className="h-1.5 w-full rounded-full bg-[var(--diverging-mid)]" aria-hidden>
                  <div className="h-1.5 rounded-full bg-[var(--series-1)]" style={{ width: `${Math.round(e.strength * 100)}%` }} />
                </div>
                <span className="text-[11px] text-text-muted">{t("rc.strength", { pct: isolate(`${Math.round(e.strength * 100)}%`) })}</span>
              </div>
            </li>
          ))}
        </ul>
      </SectionCard>

      <SectionCard title={t("rc.perspective.title")}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {(["buyer", "seller"] as const).map((who) => (
            <div key={who} className="rounded-md border border-border-hairline bg-surface-0 px-3 py-2.5">
              <p className="text-xs font-semibold text-text-secondary">{t(`rc.${who}`)}</p>
              <p className="mt-1 text-sm text-text-primary">{t(`rc.${who}.${signal}` as TranslationKey)}</p>
            </div>
          ))}
        </div>
      </SectionCard>

      <p className="text-xs text-text-muted">{t("rc.disclaimer")}</p>
    </div>
  );
}
