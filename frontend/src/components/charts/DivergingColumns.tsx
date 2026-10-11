"use client";

import { useState } from "react";
import { symmetricTicks } from "./ticks";

export interface DivergingItem {
  key: string;
  label: string;
  value: number;
  detail?: string;
}

const WIDTH = 800;
const PAD_LEFT = 48;
const PAD_RIGHT = 16;
const PAD_TOP = 20;
const PAD_BOTTOM = 28;
const MAX_BAR = 24;
const RADIUS = 4;

/**
 * Columns growing up or down from a zero baseline - for a signed deviation
 * (above vs below a reference). Diverging colors: warm above, cool below;
 * the baseline is the neutral midpoint. Only the extremes are labelled; every
 * value is in the hover tooltip and in the table next to the chart.
 */
export function DivergingColumns({
  items,
  height = 220,
  formatValue,
  legend,
  ariaLabel,
}: {
  items: DivergingItem[];
  height?: number;
  formatValue: (v: number) => string;
  legend: { positive: string; negative: string };
  ariaLabel: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (items.length === 0) return null;

  const ticks = symmetricTicks(Math.max(...items.map((d) => Math.abs(d.value)), 1));
  const maxAbs = ticks[ticks.length - 1];
  const plotH = height - PAD_TOP - PAD_BOTTOM;
  const y = (v: number) => PAD_TOP + plotH / 2 - (v / maxAbs) * (plotH / 2);
  const slot = (WIDTH - PAD_LEFT - PAD_RIGHT) / items.length;
  const barW = Math.min(MAX_BAR, slot * 0.6);
  const cx = (i: number) => PAD_LEFT + slot * i + slot / 2;
  const zero = y(0);
  const maxIdx = items.reduce((b, d, i) => (d.value > items[b].value ? i : b), 0);
  const minIdx = items.reduce((b, d, i) => (d.value < items[b].value ? i : b), 0);

  // Rounded at the data end only, square on the baseline.
  const bar = (i: number) => {
    const v = items[i].value;
    const x0 = cx(i) - barW / 2;
    const x1 = cx(i) + barW / 2;
    const yv = y(v);
    const r = Math.min(RADIUS, Math.abs(yv - zero), barW / 2);
    if (v >= 0) {
      return `M${x0},${zero} L${x0},${yv + r} Q${x0},${yv} ${x0 + r},${yv} L${x1 - r},${yv} Q${x1},${yv} ${x1},${yv + r} L${x1},${zero} Z`;
    }
    return `M${x0},${zero} L${x0},${yv - r} Q${x0},${yv} ${x0 + r},${yv} L${x1 - r},${yv} Q${x1},${yv} ${x1},${yv - r} L${x1},${zero} Z`;
  };
  const hovered = hover !== null ? items[hover] : null;

  return (
    <div className="flex flex-col gap-2" dir="ltr">
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-secondary" dir="auto">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "var(--diverging-pos)" }} aria-hidden />
          {legend.positive}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: "var(--diverging-neg)" }} aria-hidden />
          {legend.negative}
        </span>
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${WIDTH} ${height}`} className="w-full" style={{ height }} role="img" aria-label={ariaLabel}>
          {ticks.map((v, i) => (
            <g key={i}>
              <line
                x1={PAD_LEFT}
                x2={WIDTH - PAD_RIGHT}
                y1={y(v)}
                y2={y(v)}
                stroke={v === 0 ? "var(--baseline)" : "var(--grid-hairline)"}
                strokeWidth={1}
              />
              <text x={PAD_LEFT - 8} y={y(v)} textAnchor="end" dominantBaseline="middle" className="fill-text-muted text-[10px] tabular-nums">
                {formatValue(v)}
              </text>
            </g>
          ))}
          {items.map((d, i) => (
            <g key={d.key}>
              <path
                d={bar(i)}
                fill={d.value >= 0 ? "var(--diverging-pos)" : "var(--diverging-neg)"}
                opacity={hover === null || hover === i ? 1 : 0.55}
              />
              <text x={cx(i)} y={height - 8} textAnchor="middle" className="fill-text-muted text-[10px]">
                {d.label}
              </text>
              {(i === maxIdx || i === minIdx) && (
                <text
                  x={cx(i)}
                  y={d.value >= 0 ? y(d.value) - 6 : y(d.value) + 12}
                  textAnchor="middle"
                  className="fill-text-primary text-[10px] font-semibold tabular-nums"
                >
                  {formatValue(d.value)}
                </text>
              )}
              {/* Hit target: the whole slot, not just the painted bar. */}
              <rect
                x={cx(i) - slot / 2}
                y={PAD_TOP}
                width={slot}
                height={plotH}
                fill="transparent"
                tabIndex={0}
                aria-label={`${d.label}: ${formatValue(d.value)}`}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
              />
            </g>
          ))}
        </svg>
        {hovered && hover !== null && (
          <div
            className="pointer-events-none absolute top-1 rounded-md border border-border-hairline bg-surface-2 px-2.5 py-1.5 text-xs shadow-sm"
            style={{ left: `min(${(cx(hover) / WIDTH) * 100}%, calc(100% - 170px))` }}
          >
            <div className="font-semibold tabular-nums text-text-primary">{formatValue(hovered.value)}</div>
            <div className="text-text-secondary" dir="auto">
              {hovered.label}
            </div>
            {hovered.detail && (
              <div className="text-text-muted" dir="auto">
                {hovered.detail}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
