import type { TranslationKey } from "./i18n";

const compactNumber = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const plainNumber = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const integerNumber = new Intl.NumberFormat("en-US");

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return compactNumber.format(value);
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return plainNumber.format(value);
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return integerNumber.format(value);
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

type Translate = (key: TranslationKey, vars?: Record<string, string | number>) => string;

export function formatRelativeTime(iso: string | null | undefined, nowMs: number, t: Translate): string {
  if (!iso) return t("relTime.never");
  const diffSec = Math.max(0, Math.floor((nowMs - new Date(iso).getTime()) / 1000));
  if (diffSec < 5) return t("relTime.justNow");
  if (diffSec < 60) return t("relTime.secAgo", { n: diffSec });
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return t("relTime.minAgo", { n: diffMin });
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return t("relTime.hourAgo", { n: diffHr });
  return t("relTime.dayAgo", { n: Math.floor(diffHr / 24) });
}

// Time only for today; older timestamps get their date too - a bare clock
// time made a quote last seen weeks ago look like it updated this morning.
export function formatClockTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  const time = date.toLocaleTimeString("en-GB", { hour12: false });
  if (date.toDateString() === new Date().toDateString()) return time;
  return `${date.toLocaleDateString("en-CA")} ${time.slice(0, 5)}`;
}
