"use client";

import { useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { StatTile } from "@/components/StatTile";
import { BandLineChart, ROTATED_LABEL_EXTRA, type BandPoint } from "@/components/charts/BandLineChart";
import { api } from "@/lib/api";
import type { Market } from "@/lib/types";
import { formatCompact } from "@/lib/format";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import type { Contributions, ForecastResponse } from "@/lib/types";
import {
  MarketScope,
  ModelPicker,
  ModelTable,
  SectionCard,
  bestModel,
  degrees,
  isolate,
  monthLabel,
  monthName,
  price,
  signedPct,
  reasonText,
  useEndpoint,
  weekdayName,
} from "./common";

const DRIVERS: (keyof Contributions)[] = ["drift", "season", "temperature", "nowruz"];

function shortMonth(t: ReturnType<typeof useI18n>["t"], year: number, month: number): string {
  return `${monthName(t, month)} ${String(year).slice(2)}`;
}

export function ForecastTab({ market }: { market: Market }) {
  const { t } = useI18n();
  const { data, error } = useEndpoint(() => api.forecast(market));

  if (error) return <EmptyState title={t("fc.failed")} detail={error} />;
  if (!data) return <EmptyState title={t("analytics.loading")} />;
  if (data.status !== "ok") {
    return <EmptyState title={t("fc.failed")} detail={t("fc.insufficient", { reason: reasonText(t, data.monthly.reason) })} />;
  }
  return (
    <div className="flex flex-col gap-6">
      <MarketScope series={data.series} />
      <MonthlySection data={data} />
      <ShortTermSection data={data} />
      <SectionCard title={t("fc.caveats.title")}>
        <ul className="list-inside list-disc space-y-1 text-xs text-text-secondary">
          <li>{t("fc.caveat.1")}</li>
          <li>{t("fc.caveat.2")}</li>
          <li>{t("fc.caveat.3")}</li>
          <li>{t("fc.caveat.4")}</li>
        </ul>
      </SectionCard>
    </div>
  );
}

function MonthlySection({ data }: { data: ForecastResponse }) {
  const { t } = useI18n();
  // Next month by default; months 2-6 on request (wider uncertainty).
  const [showAll, setShowAll] = useState(false);
  // null = follow the default (best model for the current view).
  const [chosenModel, setChosenModel] = useState<string | null>(null);
  const m = data.monthly;
  if (m.status !== "ok" || !m.origin_label || m.origin_price === null || !m.validation) {
    return <EmptyState title={t("fc.title.monthly")} detail={t("fc.insufficient", { reason: reasonText(t, m.reason) })} />;
  }
  const validation = m.validation;
  // "Best" depends on what is shown: next-month error, or the 1-6 month average.
  const horizonKey = showAll ? undefined : "h1";
  const best = bestModel(validation, horizonKey);
  const activeModel = chosenModel ?? best ?? validation.selected_model ?? "naive";
  const modelPoints = m.models[activeModel] ?? m.points;
  const originPrice = m.origin_price;
  const visible = showAll ? modelPoints : modelPoints.slice(0, 1);
  const next = modelPoints[0];
  const threeOut = showAll ? modelPoints.find((p) => p.horizon_months === 3) : undefined;
  const lastHistory = data.history[data.history.length - 1];

  const pricePoints: BandPoint[] = [
    ...m.history.map((h) => ({ key: h.label, label: shortMonth(t, h.year, h.month), value: h.price })),
    ...visible.map((p) => ({
      key: p.label,
      label: shortMonth(t, p.year, p.month),
      value: p.price,
      low: p.low,
      high: p.high,
      projected: true,
    })),
  ];
  const tempPoints: BandPoint[] = [
    ...m.history
      .filter((h) => h.t_mean !== null)
      .map((h) => ({
        key: h.label,
        label: shortMonth(t, h.year, h.month),
        value: h.t_mean as number,
        // The in-progress month is an estimate (observed so far + forecast/normal).
        projected: m.origin_partial && h.label === m.origin_label,
      })),
    ...visible.map((p) => ({ key: p.label, label: shortMonth(t, p.year, p.month), value: p.t_mean, projected: true })),
  ];
  const deg = (v: number) => degrees(v);

  return (
    <SectionCard title={showAll ? t("fc.title.monthly") : t("fc.title.nextMonth")}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-md border border-border-hairline p-0.5 text-xs" role="group">
          {[false, true].map((all) => (
            <button
              key={String(all)}
              type="button"
              onClick={() => setShowAll(all)}
              aria-pressed={showAll === all}
              className={`rounded px-3 py-1.5 font-medium ${
                showAll === all ? "bg-surface-2 text-text-primary shadow-sm" : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {all ? t("fc.toggle.allMonths", { n: m.points.length }) : t("fc.toggle.nextMonth")}
            </button>
          ))}
        </div>
        <p className="text-xs text-text-muted">{t("fc.toggle.note")}</p>
      </div>
      <div className="mb-4">
        <ModelPicker validation={validation} horizonKey={horizonKey} active={activeModel} best={best} onChange={setChosenModel} />
      </div>

      <div className={`grid grid-cols-2 gap-3 ${showAll ? "lg:grid-cols-4" : "lg:grid-cols-3"}`}>
        <StatTile label={t("fc.lastPrice")} value={price(data.last_price)} delta={lastHistory?.jalali ?? null} />
        <StatTile
          label={t("fc.currentMonth", { month: monthLabel(t, m.origin_label) })}
          value={price(originPrice)}
          delta={m.origin_partial ? t("fc.partial", { n: m.origin_trading_days }) : null}
        />
        {next && (
          <StatTile
            label={t("fc.forecastFor", { month: monthLabel(t, next.label) })}
            value={price(next.price)}
            delta={`${signedPct(100 * (next.price / originPrice - 1))} · ${t("fc.range", { low: price(next.low), high: price(next.high) })}`}
          />
        )}
        {threeOut && (
          <StatTile
            label={t("fc.forecastFor", { month: monthLabel(t, threeOut.label) })}
            value={price(threeOut.price)}
            delta={`${signedPct(100 * (threeOut.price / originPrice - 1))} · ${t("fc.range", { low: price(threeOut.low), high: price(threeOut.high) })}`}
          />
        )}
      </div>

      <div className="mt-5">
        <BandLineChart
          points={pricePoints}
          color="var(--series-1)"
          formatValue={price}
          formatAxis={(v) => formatCompact(v)}
          legend={{ observed: t("fc.chart.observed"), projected: t("fc.chart.forecast"), band: t("fc.chart.band") }}
          ariaLabel={t("fc.title.monthly")}
          height={240 + ROTATED_LABEL_EXTRA}
          tickEvery={1}
          rotateLabels
        />
      </div>

      <div className="mt-5">
        <p className="mb-1 text-xs font-medium text-text-secondary">{t("fc.chart.temp")}</p>
        <BandLineChart
          points={tempPoints}
          color="var(--series-2)"
          height={160 + ROTATED_LABEL_EXTRA}
          formatValue={deg}
          formatAxis={(v) => isolate(`${Math.round(v)}°`)}
          legend={{ observed: t("fc.chart.tempObserved"), projected: t("fc.chart.tempExpected") }}
          ariaLabel={t("fc.chart.temp")}
          tickEvery={1}
          rotateLabels
        />
      </div>

      <div className="mt-5 overflow-x-auto rounded-md border border-border-hairline">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
              <th className="px-3 py-2 text-start font-medium">{t("fc.col.month")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("fc.col.forecast")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("fc.col.range")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("fc.col.temp")}</th>
              <th className="px-3 py-2 text-start font-medium">{t("fc.col.drivers")}</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((p) => (
              <tr key={p.label} className="border-b border-border-hairline last:border-0">
                <td className="px-3 py-2 text-start font-medium text-text-primary">{monthLabel(t, p.label)}</td>
                <td className="px-3 py-2 text-end tabular-nums text-text-primary">
                  {price(p.price)}{" "}
                  <span className="text-xs text-text-muted">{signedPct(100 * (p.price / originPrice - 1))}</span>
                </td>
                <td className="px-3 py-2 text-end tabular-nums text-text-secondary">
                  {price(p.low)} – {price(p.high)}
                </td>
                <td className="px-3 py-2 text-end text-text-secondary">
                  <span className="tabular-nums">{deg(p.t_mean)}</span>{" "}
                  <span className="text-[11px] text-text-muted">({t(`fc.tsource.${p.t_source}` as TranslationKey)})</span>
                </td>
                <td className="px-3 py-2 text-start text-xs text-text-secondary">
                  {DRIVERS.filter((k) => p.contributions_pct[k] !== undefined && Math.abs(p.contributions_pct[k] as number) >= 0.05)
                    .map((k) => `${t(`fc.driver.${k}` as TranslationKey)} ${signedPct(p.contributions_pct[k])}`)
                    .join(" · ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-5">
        <h3 className="text-sm font-semibold text-text-primary">{t("fc.validation.title")}</h3>
        <p className="mb-2 mt-1 text-xs text-text-muted">
          {t("fc.validation.monthly", {
            n: validation.origins,
            start: validation.start ? monthLabel(t, validation.start) : "—",
            end: validation.end ? monthLabel(t, validation.end) : "—",
          })}
        </p>
        {showAll ? (
          <ModelTable
            validation={validation}
            horizons={[1, 3, 6].map((h) => ({ key: `h${h}`, label: t("fc.h.months", { n: h }) }))}
            active={activeModel}
            best={best}
          />
        ) : (
          <ModelTable
            validation={validation}
            horizons={[]}
            focus={{ key: "h1", label: t("fc.h.months", { n: 1 }) }}
            active={activeModel}
            best={best}
          />
        )}
      </div>
    </SectionCard>
  );
}

function ShortTermSection({ data }: { data: ForecastResponse }) {
  const { t } = useI18n();
  const [chosenModel, setChosenModel] = useState<string | null>(null);
  const d = data.daily;
  if (d.status !== "ok" || !d.validation) {
    return <EmptyState title={t("fc.short.title")} detail={t("fc.insufficient", { reason: reasonText(t, d.reason) })} />;
  }
  const best = bestModel(d.validation);
  const activeModel = chosenModel ?? best ?? "naive";
  const modelPoints = d.models[activeModel] ?? d.points;
  const recent = data.history.slice(-60);
  const points: BandPoint[] = [
    ...recent.map((h) => ({ key: h.day, label: h.jalali.slice(5), value: h.price })),
    ...modelPoints.map((p) => ({ key: p.day, label: p.jalali.slice(5), value: p.price, low: p.low, high: p.high, projected: true })),
  ];

  return (
    <SectionCard
      title={t("fc.short.title")}
      note={
        best === "naive"
          ? t("fc.short.note.naive")
          : t("fc.short.note.model", { model: t(`fc.model.${best}` as TranslationKey) })
      }
    >
      <div className="mb-4">
        <ModelPicker validation={d.validation} active={activeModel} best={best} onChange={setChosenModel} />
      </div>
      <BandLineChart
        points={points}
        color="var(--series-1)"
        height={200}
        formatValue={price}
        formatAxis={(v) => formatCompact(v)}
        legend={{ observed: t("fc.short.chart.observed"), projected: t("fc.chart.forecast"), band: t("fc.chart.band") }}
        ariaLabel={t("fc.short.title")}
        tickEvery={10}
      />
      <div className="mt-4 overflow-x-auto rounded-md border border-border-hairline">
        <table className="w-full min-w-[420px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
              <th className="px-3 py-2 text-start font-medium">{t("fc.col.day")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("fc.col.forecast")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("fc.col.range")}</th>
              <th className="px-3 py-2 text-end font-medium">{t("fc.col.t7")}</th>
            </tr>
          </thead>
          <tbody>
            {modelPoints.map((p) => (
              <tr key={p.day} className="border-b border-border-hairline last:border-0">
                <td className="px-3 py-2 text-start text-text-primary">
                  {weekdayName(t, p.day)} <span className="tabular-nums text-text-muted">{p.jalali}</span>
                </td>
                <td className="px-3 py-2 text-end tabular-nums text-text-primary">{price(p.price)}</td>
                <td className="px-3 py-2 text-end tabular-nums text-text-secondary">
                  {price(p.low)} – {price(p.high)}
                </td>
                <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{p.t7 === null ? "—" : degrees(p.t7)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-5">
        <h3 className="text-sm font-semibold text-text-primary">{t("fc.validation.title")}</h3>
        <p className="mb-2 mt-1 text-xs text-text-muted">
          {t("fc.validation.daily", { n: d.validation.origins, start: d.validation.start ?? "—", end: d.validation.end ?? "—" })}
        </p>
        <ModelTable
          validation={d.validation}
          horizons={["1-3", "4-7", "8-14"].map((key) => ({ key, label: t("fc.h.days", { range: key }) }))}
          active={activeModel}
          best={best}
        />
      </div>
    </SectionCard>
  );
}
