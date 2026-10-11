"use client";

import { EmptyState } from "@/components/EmptyState";
import { StatTile } from "@/components/StatTile";
import { DivergingColumns } from "@/components/charts/DivergingColumns";
import { api } from "@/lib/api";
import { formatInt } from "@/lib/format";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import { MarketScope, SectionCard, degrees, isolate, monthName, price, signedPct, useEndpoint } from "./common";

const FEATURE_ORDER = [
  "momentum_20d_pct",
  "volatility_20d_pct",
  "level_vs_year_pct",
  "temperature_7d",
  "temperature_change_14d",
] as const;

function tempBinLabel(low: number, high: number): string {
  if (low <= -50) return `<${high}`;
  if (high >= 60) return `${low}+`;
  return `${low}–${high}`;
}

export function PatternsTab() {
  const { t, lang } = useI18n();
  const { data, error } = useEndpoint(api.patterns);
  // Reading direction decides which way "from -> to" points.
  const arrow = lang === "fa" ? "←" : "→";
  const listSep = lang === "fa" ? "، " : ", ";

  if (error) return <EmptyState title={t("pt.failed")} detail={error} />;
  if (!data) return <EmptyState title={t("analytics.loading")} />;
  if (data.status !== "ok") {
    return <EmptyState title={t("pt.failed")} detail={t("fc.insufficient", { reason: data.reason ?? "—" })} />;
  }

  const featureValue = (key: (typeof FEATURE_ORDER)[number], v: number | undefined) => {
    if (v === undefined) return "—";
    if (key === "temperature_7d") return degrees(v);
    if (key === "temperature_change_14d") return degrees(v, true);
    if (key === "volatility_20d_pct") return isolate(`${v.toFixed(1)}%`);
    return signedPct(v);
  };
  const summary = data.analogue_summary;
  const n = Number(summary.n ?? 0);
  const up20 = summary.share_up_20d;

  return (
    <div className="flex flex-col gap-6">
      <MarketScope series={data.series} />

      <SectionCard title={t("pt.current.title", { date: data.current_day ?? "—" })}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {FEATURE_ORDER.map((key) => (
            <StatTile key={key} label={t(`pt.feat.${key}` as TranslationKey)} value={featureValue(key, data.current_features[key])} />
          ))}
        </div>
      </SectionCard>

      <SectionCard title={t("pt.seasonal.title")} note={t("pt.seasonal.note", { years: data.seasonal_years.join(listSep) })}>
        <DivergingColumns
          items={data.seasonal.map((m) => ({
            key: String(m.month),
            label: monthName(t, m.month),
            value: m.mean_deviation_pct,
            detail: `${t("pt.col.consistency")}: ${Math.round(m.consistency * 100)}% · ${t("pt.col.years")}: ${m.years}`,
          }))}
          formatValue={(v) => signedPct(v, 0)}
          legend={{ positive: t("pt.above"), negative: t("pt.below") }}
          ariaLabel={t("pt.seasonal.title")}
        />
        <div className="mt-4 overflow-x-auto rounded-md border border-border-hairline">
          <table className="w-full min-w-[420px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
                <th className="px-3 py-2 text-start font-medium">{t("pt.col.month")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.deviation")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.consistency")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.years")}</th>
              </tr>
            </thead>
            <tbody>
              {data.seasonal.map((m) => (
                <tr key={m.month} className="border-b border-border-hairline last:border-0">
                  <td className="px-3 py-1.5 text-start text-text-primary">{monthName(t, m.month)}</td>
                  <td className="px-3 py-1.5 text-end tabular-nums text-text-primary">{signedPct(m.mean_deviation_pct)}</td>
                  <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">{Math.round(m.consistency * 100)}%</td>
                  <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">{m.years}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard
        title={t("pt.temp.title")}
        note={t("pt.temp.note", {
          r: data.temperature_correlation === null ? "—" : data.temperature_correlation.toFixed(2),
          n: formatInt(data.temperature_points),
        })}
      >
        <DivergingColumns
          items={data.temperature_bins.map((b) => ({
            key: `${b.low}`,
            label: `${tempBinLabel(b.low, b.high)}°C`,
            value: b.mean_deviation_pct,
            detail: `${t("pt.col.days")}: ${formatInt(b.n)}`,
          }))}
          height={200}
          formatValue={(v) => signedPct(v, 0)}
          legend={{ positive: t("pt.above"), negative: t("pt.below") }}
          ariaLabel={t("pt.temp.title")}
        />
        <div className="mt-4 overflow-x-auto rounded-md border border-border-hairline">
          <table className="w-full min-w-[360px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
                <th className="px-3 py-2 text-start font-medium">{t("pt.col.tempBin")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.deviation")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.days")}</th>
              </tr>
            </thead>
            <tbody>
              {data.temperature_bins.map((b) => (
                <tr key={b.low} className="border-b border-border-hairline last:border-0">
                  <td className="ltr-content px-3 py-1.5 text-start text-text-primary">{tempBinLabel(b.low, b.high)}</td>
                  <td className="px-3 py-1.5 text-end tabular-nums text-text-primary">{signedPct(b.mean_deviation_pct)}</td>
                  <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">{formatInt(b.n)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SectionCard title={t("pt.transitions.title")}>
          <div className="overflow-x-auto rounded-md border border-border-hairline">
            <table className="w-full min-w-[360px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
                  <th className="px-3 py-2 text-start font-medium">{t("pt.col.fromTo")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("pt.col.avgChange")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("pt.col.upYears")}</th>
                </tr>
              </thead>
              <tbody>
                {data.transitions.map((tr) => (
                  <tr key={tr.from_month} className="border-b border-border-hairline last:border-0">
                    <td className="px-3 py-1.5 text-start text-text-primary">
                      {monthName(t, tr.from_month)} {arrow} {monthName(t, tr.to_month)}
                    </td>
                    <td className="px-3 py-1.5 text-end tabular-nums text-text-primary">{signedPct(tr.mean_change_pct)}</td>
                    <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">
                      {Math.round(tr.share_up * tr.years)} / {tr.years}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title={t("pt.weekday.title")} note={t("pt.weekday.note", { since: data.weekday_since ?? "—" })}>
          <div className="overflow-x-auto rounded-md border border-border-hairline">
            <table className="w-full min-w-[320px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
                  <th className="px-3 py-2 text-start font-medium">{t("pt.col.weekday")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("pt.col.avgChange")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("pt.col.shareUp")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("pt.col.n")}</th>
                </tr>
              </thead>
              <tbody>
                {data.weekday.map((w) => (
                  <tr key={w.weekday} className="border-b border-border-hairline last:border-0">
                    <td className="px-3 py-1.5 text-start text-text-primary">{t(`weekday.${w.weekday}` as TranslationKey)}</td>
                    <td className="px-3 py-1.5 text-end tabular-nums text-text-primary">{signedPct(w.mean_change_pct, 2)}</td>
                    <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">{Math.round(w.share_up * 100)}%</td>
                    <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">{w.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      </div>

      <SectionCard title={t("pt.analogues.title")} note={t("pt.analogues.note")}>
        {n > 0 && up20 !== null && up20 !== undefined && (
          <p className="mb-3 text-sm font-medium text-text-primary">
            {t("pt.analogues.summary", {
              up: Math.round(up20 * n),
              n,
              median: signedPct(summary.median_20d_pct ?? null),
            })}
          </p>
        )}
        <div className="overflow-x-auto rounded-md border border-border-hairline">
          <table className="w-full min-w-[600px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
                <th className="px-3 py-2 text-start font-medium">{t("pt.col.date")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.similarity")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.price")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.after1")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.after5")}</th>
                <th className="px-3 py-2 text-end font-medium">{t("pt.col.after20")}</th>
              </tr>
            </thead>
            <tbody>
              {data.analogues.map((a) => (
                <tr key={a.day} className="border-b border-border-hairline last:border-0">
                  <td className="px-3 py-1.5 text-start tabular-nums text-text-primary">{a.jalali}</td>
                  <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">{Math.round(a.similarity)}%</td>
                  <td className="px-3 py-1.5 text-end tabular-nums text-text-secondary">{price(a.price)}</td>
                  {(["1d", "5d", "20d"] as const).map((h) => (
                    <td key={h} className="px-3 py-1.5 text-end tabular-nums text-text-primary">
                      {signedPct(a.outcomes_pct[h])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}
