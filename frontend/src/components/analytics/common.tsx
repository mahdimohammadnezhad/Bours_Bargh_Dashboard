"use client";

import { useEffect, useState } from "react";
import { formatInt } from "@/lib/format";
import { useI18n, type TranslationKey } from "@/lib/i18n";
import type { ModelScore, SeriesInfo, Validation } from "@/lib/types";

type Translate = ReturnType<typeof useI18n>["t"];

export function useEndpoint<T>(load: () => Promise<T>): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
    // `load` is a stable module-level api call; fetch once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { data, error };
}

export function monthName(t: Translate, month: number): string {
  return t(`month.${month}` as TranslationKey);
}

/** "1405/08" -> "آبان ۱۴۰۵" / "Aban 1405". */
export function monthLabel(t: Translate, label: string): string {
  const [year, month] = label.split("/").map(Number);
  return `${monthName(t, month)} ${year}`;
}

/** Weekday name for an ISO date. i18n keys use Python numbering (Mon=0),
 * matching the backend; JavaScript's getDay() has Sun=0. */
export function weekdayName(t: Translate, isoDay: string): string {
  const js = new Date(`${isoDay}T12:00:00`).getDay();
  return t(`weekday.${(js + 6) % 7}` as TranslationKey);
}

/** Wrap in Unicode LTR isolate marks (invisible). Without them a signed
 * number inside Persian text is reordered by the bidi algorithm - "-4.9°"
 * shows as "4.9°-" and "+53%" as "53%+". Works inside translated sentences
 * and SVG text, where a wrapping element isn't an option. */
export function isolate(text: string): string {
  return `⁦${text}⁩`;
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return isolate(`${sign}${Math.abs(value).toFixed(digits)}%`);
}

export function degrees(value: number, signed = false): string {
  const sign = signed ? (value > 0 ? "+" : value < 0 ? "−" : "") : value < 0 ? "−" : "";
  return isolate(`${sign}${Math.abs(value).toFixed(1)}°`);
}

export function price(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : formatInt(Math.round(value));
}

export function MarketScope({ series }: { series: SeriesInfo }) {
  const { t } = useI18n();
  return (
    <p className="text-xs text-text-muted">
      {t("analytics.marketScope", {
        first: series.first_day ?? "—",
        last: series.last_day ?? "—",
        n: series.trading_days,
      })}{" "}
      · {t("analytics.unit")}
    </p>
  );
}

export function SectionCard({ title, note, children }: { title: string; note?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border-hairline bg-surface-1 p-4">
      <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
      {note && <p className="mt-1 text-xs text-text-muted">{note}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** Validated error used to rank models: one horizon's MAPE, or the all-horizon MAPE. */
export function modelError(score: ModelScore, horizonKey?: string): number | null {
  if (!horizonKey) return score.mape;
  return score.by_horizon[horizonKey]?.mape ?? null;
}

/** Lowest validated error - the default model for that view. */
export function bestModel(validation: Validation, horizonKey?: string): string | null {
  let best: ModelScore | null = null;
  for (const s of validation.scores) {
    const e = modelError(s, horizonKey);
    if (e !== null && (best === null || e < (modelError(best, horizonKey) as number))) best = s;
  }
  return best?.model ?? validation.selected_model;
}

/** One chip per validated model with its error; the best is marked, the active one pressed. */
export function ModelPicker({
  validation,
  horizonKey,
  active,
  best,
  onChange,
}: {
  validation: Validation;
  horizonKey?: string;
  active: string;
  best: string | null;
  onChange: (model: string) => void;
}) {
  const { t } = useI18n();
  const options = validation.scores
    .map((s) => ({ model: s.model, error: modelError(s, horizonKey) }))
    .filter((o): o is { model: string; error: number } => o.error !== null)
    .sort((a, b) => a.error - b.error);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t("fc.model.pick")}>
        <span className="text-xs font-medium text-text-secondary">{t("fc.model.pick")}</span>
        {options.map((o) => {
          const pressed = o.model === active;
          return (
            <button
              key={o.model}
              type="button"
              role="radio"
              aria-checked={pressed}
              onClick={() => onChange(o.model)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
                pressed
                  ? "border-[var(--series-1)] bg-[var(--series-1)]/10 font-semibold text-text-primary"
                  : "border-border-hairline text-text-secondary hover:text-text-primary"
              }`}
            >
              {t(`fc.model.${o.model}` as TranslationKey)}
              <span className="tabular-nums text-text-muted">{o.error.toFixed(1)}%</span>
              {o.model === best && <span className="text-[10px] text-text-muted">✓ {t("fc.best")}</span>}
            </button>
          );
        })}
      </div>
      <p className="text-[11px] text-text-muted">{t("fc.model.pick.note")}</p>
    </div>
  );
}

function ModelNameCell({ model, active, best }: { model: string; active?: string; best?: string | null }) {
  const { t } = useI18n();
  return (
    <td className="px-3 py-2 text-start text-text-primary">
      <span className={model === active ? "font-semibold" : ""}>{t(`fc.model.${model}` as TranslationKey)}</span>
      {model === best && (
        <span className="ms-2 rounded-full border border-border-hairline px-1.5 py-0.5 text-[10px] text-text-secondary">
          ✓ {t("fc.best")}
        </span>
      )}
      {model === active && model !== best && (
        <span className="ms-2 rounded-full border border-[var(--series-1)] px-1.5 py-0.5 text-[10px] text-text-secondary">
          {t("fc.shown")}
        </span>
      )}
    </td>
  );
}

export function ModelTable({
  validation,
  horizons,
  focus,
  active,
  best = validation.selected_model,
}: {
  validation: Validation;
  horizons: { key: string; label: string }[];
  /** Show only this horizon's numbers (e.g. next month), not the 1-6 month average. */
  focus?: { key: string; label: string };
  /** The model currently drawn (row highlighted). */
  active?: string;
  /** The lowest-error model (badge). */
  best?: string | null;
}) {
  const { t } = useI18n();
  if (focus) return <FocusedModelTable validation={validation} focus={focus} active={active} best={best} />;
  return (
    <div className="overflow-x-auto rounded-md border border-border-hairline">
      <table className="w-full min-w-[520px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
            <th className="px-3 py-2 text-start font-medium">{t("fc.col.model")}</th>
            <th className="px-3 py-2 text-end font-medium">{t("fc.col.mape")}</th>
            {horizons.map((h) => (
              <th key={h.key} className="px-3 py-2 text-end font-medium">
                {h.label}
              </th>
            ))}
            <th className="px-3 py-2 text-end font-medium">{t("fc.col.direction")}</th>
          </tr>
        </thead>
        <tbody>
          {validation.scores.map((s) => {
            return (
              <tr key={s.model} className={`border-b border-border-hairline last:border-0 ${s.model === active ? "bg-surface-0" : ""}`}>
                <ModelNameCell model={s.model} active={active} best={best} />
                <td className="px-3 py-2 text-end tabular-nums text-text-primary">{s.mape.toFixed(1)}%</td>
                {horizons.map((h) => (
                  <td key={h.key} className="px-3 py-2 text-end tabular-nums text-text-secondary">
                    {s.by_horizon[h.key] ? `${s.by_horizon[h.key].mape.toFixed(1)}%` : "—"}
                  </td>
                ))}
                <td className="px-3 py-2 text-end tabular-nums text-text-secondary">
                  {s.directional_accuracy === null ? "—" : `${Math.round(s.directional_accuracy)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="border-t border-border-hairline px-3 py-1.5 text-[11px] text-text-muted">
        n = {formatInt(validation.scores[0]?.n ?? 0)}
      </p>
    </div>
  );
}

function FocusedModelTable({
  validation,
  focus,
  active,
  best,
}: {
  validation: Validation;
  focus: { key: string; label: string };
  active?: string;
  best?: string | null;
}) {
  const { t } = useI18n();
  const rows = validation.scores
    .filter((s) => s.by_horizon[focus.key])
    .sort((a, b) => a.by_horizon[focus.key].mape - b.by_horizon[focus.key].mape);
  return (
    <div className="overflow-x-auto rounded-md border border-border-hairline">
      <table className="w-full min-w-[480px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border-hairline bg-surface-0 text-xs text-text-muted">
            <th className="px-3 py-2 text-start font-medium">{t("fc.col.model")}</th>
            <th className="px-3 py-2 text-end font-medium">
              {t("fc.col.mape")} · {focus.label}
            </th>
            <th className="px-3 py-2 text-end font-medium">{t("fc.col.mae")}</th>
            <th className="px-3 py-2 text-end font-medium">{t("fc.col.direction")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const h = s.by_horizon[focus.key];
            return (
              <tr key={s.model} className={`border-b border-border-hairline last:border-0 ${s.model === active ? "bg-surface-0" : ""}`}>
                <ModelNameCell model={s.model} active={active} best={best} />
                <td className="px-3 py-2 text-end tabular-nums text-text-primary">{h.mape.toFixed(1)}%</td>
                <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{formatInt(Math.round(h.mae))}</td>
                <td className="px-3 py-2 text-end tabular-nums text-text-secondary">
                  {h.directional_accuracy === null ? "—" : `${Math.round(h.directional_accuracy)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="border-t border-border-hairline px-3 py-1.5 text-[11px] text-text-muted">
        n = {formatInt(rows[0]?.by_horizon[focus.key].n ?? 0)}
      </p>
    </div>
  );
}
