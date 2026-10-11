"use client";

import { useMemo, useRef, useState } from "react";
import { niceTicks } from "./ticks";

export interface BandPoint {
  key: string;
  label: string;
  value: number;
  low?: number;
  high?: number;
  projected?: boolean;
}

const WIDTH = 800;
const PAD_LEFT = 56;
const PAD_RIGHT = 64; // room for the end label
const PAD_TOP = 16;
const PAD_BOTTOM = 28;
// Rotated labels need a taller axis band; callers add the same amount to
// `height` so the plot itself keeps its size.
export const ROTATED_LABEL_EXTRA = 36;

/**
 * One measure over an ordered x (months or trading days): an observed
 * segment (solid), a projected segment (dashed, continuing from the last
 * observation) and an optional range band around the projection. One
 * y-axis only; a second measure gets its own chart.
 */
export function BandLineChart({
  points,
  color,
  height = 240,
  formatValue,
  formatAxis = formatValue,
  legend,
  ariaLabel,
  tickEvery = 1,
  rotateLabels = false,
}: {
  points: BandPoint[];
  color: string;
  height?: number;
  formatValue: (v: number) => string;
  formatAxis?: (v: number) => string;
  legend: { observed: string; projected?: string; band?: string };
  ariaLabel: string;
  tickEvery?: number;
  /** Slant x labels 45° so every point can be labelled (e.g. every month). */
  rotateLabels?: boolean;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const padBottom = PAD_BOTTOM + (rotateLabels ? ROTATED_LABEL_EXTRA : 0);

  const geometry = useMemo(() => {
    const values = points.flatMap((p) => [p.value, p.low ?? p.value, p.high ?? p.value]);
    const ticks = niceTicks(Math.min(...values), Math.max(...values));
    const minV = ticks[0];
    const maxV = ticks[ticks.length - 1];
    const n = points.length;
    const x = (i: number) => PAD_LEFT + (n <= 1 ? 0 : (i / (n - 1)) * (WIDTH - PAD_LEFT - PAD_RIGHT));
    const y = (v: number) => height - padBottom - ((v - minV) / (maxV - minV || 1)) * (height - PAD_TOP - padBottom);
    return { ticks, x, y };
  }, [points, height, padBottom]);

  if (points.length < 2) return null;
  const { ticks, x, y } = geometry;

  const lastObserved = points.reduce((acc, p, i) => (p.projected ? acc : i), -1);
  const observed = points.slice(0, lastObserved + 1);
  const projectedIdx = points.map((p, i) => (p.projected ? i : -1)).filter((i) => i >= 0);
  const path = (idx: number[]) => idx.map((i, k) => `${k === 0 ? "M" : "L"}${x(i)},${y(points[i].value)}`).join(" ");
  const observedPath = path(observed.map((_, i) => i));
  const projectedPath = projectedIdx.length ? path([...(lastObserved >= 0 ? [lastObserved] : []), ...projectedIdx]) : "";
  const bandIdx = projectedIdx.filter((i) => points[i].low !== undefined && points[i].high !== undefined);
  const bandPath = bandIdx.length
    ? [
        ...(lastObserved >= 0 ? [`M${x(lastObserved)},${y(points[lastObserved].value)}`] : []),
        ...bandIdx.map((i, k) => `${k === 0 && lastObserved < 0 ? "M" : "L"}${x(i)},${y(points[i].high!)}`),
        ...[...bandIdx].reverse().map((i) => `L${x(i)},${y(points[i].low!)}`),
        "Z",
      ].join(" ")
    : "";

  const end = points.length - 1;
  const hovered = hover !== null ? points[hover] : null;

  const onMove: React.PointerEventHandler<SVGSVGElement> = (event) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    let best = 0;
    points.forEach((_, i) => {
      if (Math.abs(x(i) - relX) < Math.abs(x(best) - relX)) best = i;
    });
    setHover(best);
  };

  return (
    <div className="flex flex-col gap-2" dir="ltr">
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-secondary" dir="auto">
        <span className="flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden>
            <line x1="1" x2="17" y1="3" y2="3" stroke={color} strokeWidth="2" strokeLinecap="round" />
          </svg>
          {legend.observed}
        </span>
        {legend.projected && projectedIdx.length > 0 && (
          <span className="flex items-center gap-1.5">
            <svg width="18" height="6" aria-hidden>
              <line x1="1" x2="17" y1="3" y2="3" stroke={color} strokeWidth="2" strokeDasharray="4 3" strokeLinecap="round" />
            </svg>
            {legend.projected}
          </span>
        )}
        {legend.band && bandPath && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: color, opacity: 0.18 }} aria-hidden />
            {legend.band}
          </span>
        )}
      </div>
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${height}`}
          className="w-full touch-none"
          style={{ height }}
          role="img"
          aria-label={ariaLabel}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((v, i) => (
            <g key={i}>
              <line x1={PAD_LEFT} x2={WIDTH - PAD_RIGHT} y1={y(v)} y2={y(v)} stroke="var(--grid-hairline)" strokeWidth={1} />
              <text x={PAD_LEFT - 8} y={y(v)} textAnchor="end" dominantBaseline="middle" className="fill-text-muted text-[10px] tabular-nums">
                {formatAxis(v)}
              </text>
            </g>
          ))}
          {/* Counted back from the last point so it is always labelled
              without crowding the label before it. */}
          {points.map((p, i) =>
            (end - i) % tickEvery === 0 ? (
              rotateLabels ? (
                <text
                  key={p.key}
                  x={x(i)}
                  y={height - padBottom + 14}
                  textAnchor="end"
                  transform={`rotate(-45 ${x(i)} ${height - padBottom + 14})`}
                  className="fill-text-muted text-[10px]"
                >
                  {p.label}
                </text>
              ) : (
                <text key={p.key} x={x(i)} y={height - 8} textAnchor="middle" className="fill-text-muted text-[10px]">
                  {p.label}
                </text>
              )
            ) : null,
          )}

          {bandPath && <path d={bandPath} fill={color} opacity={0.12} stroke="none" />}
          {observedPath && <path d={observedPath} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
          {projectedPath && (
            <path d={projectedPath} fill="none" stroke={color} strokeWidth={2} strokeDasharray="6 4" strokeLinejoin="round" strokeLinecap="round" />
          )}

          {lastObserved >= 0 && (
            <circle cx={x(lastObserved)} cy={y(points[lastObserved].value)} r={4} fill={color} stroke="var(--surface-1)" strokeWidth={2} />
          )}
          <circle cx={x(end)} cy={y(points[end].value)} r={4} fill={color} stroke="var(--surface-1)" strokeWidth={2} />
          <text x={x(end) + 8} y={y(points[end].value)} dominantBaseline="middle" className="fill-text-primary text-[11px] font-semibold tabular-nums">
            {formatValue(points[end].value)}
          </text>

          {hovered && hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover)} x2={x(hover)} y1={PAD_TOP} y2={height - padBottom} stroke="var(--baseline)" strokeWidth={1} />
              <circle cx={x(hover)} cy={y(hovered.value)} r={5} fill={color} stroke="var(--surface-1)" strokeWidth={2} />
            </g>
          )}
        </svg>

        {hovered && hover !== null && (
          <div
            className="pointer-events-none absolute top-1 min-w-[120px] rounded-md border border-border-hairline bg-surface-2 px-2.5 py-1.5 text-xs shadow-sm"
            style={{ left: `min(${(x(hover) / WIDTH) * 100}%, calc(100% - 150px))` }}
          >
            <div className="font-semibold tabular-nums text-text-primary">{formatValue(hovered.value)}</div>
            {hovered.low !== undefined && hovered.high !== undefined && (
              <div className="tabular-nums text-text-secondary">
                {formatValue(hovered.low)} – {formatValue(hovered.high)}
              </div>
            )}
            <div className="flex items-center gap-1.5 text-text-muted">
              <svg width="12" height="4" aria-hidden>
                <line x1="1" x2="11" y1="2" y2="2" stroke={color} strokeWidth="2" strokeDasharray={hovered.projected ? "3 2" : undefined} />
              </svg>
              {hovered.label} · {hovered.projected ? legend.projected ?? "" : legend.observed}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
