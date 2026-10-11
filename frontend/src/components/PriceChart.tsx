"use client";

import { useMemo, useRef, useState } from "react";
import { formatPrice } from "@/lib/format";

interface Point {
  observed_at: string;
  last_price: number | null;
}

const WIDTH = 800;
const HEIGHT = 260;
const PAD_LEFT = 56;
const PAD_RIGHT = 16;
const PAD_TOP = 16;
const PAD_BOTTOM = 28;

export function PriceChart({ points, seriesLabel }: { points: Point[]; seriesLabel: string }) {
  const containerRef = useRef<SVGSVGElement | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const clean = useMemo(
    () =>
      points
        .filter((p): p is { observed_at: string; last_price: number } => p.last_price !== null)
        .map((p) => ({ t: new Date(p.observed_at).getTime(), v: p.last_price })),
    [points],
  );

  if (clean.length < 2) {
    return null;
  }

  const minT = clean[0].t;
  const maxT = clean[clean.length - 1].t;
  const minVRaw = Math.min(...clean.map((p) => p.v));
  const maxVRaw = Math.max(...clean.map((p) => p.v));
  const pad = (maxVRaw - minVRaw) * 0.08 || Math.abs(maxVRaw) * 0.05 || 1;
  const minV = minVRaw - pad;
  const maxV = maxVRaw + pad;

  const x = (t: number) =>
    PAD_LEFT + ((t - minT) / (maxT - minT || 1)) * (WIDTH - PAD_LEFT - PAD_RIGHT);
  const y = (v: number) =>
    HEIGHT - PAD_BOTTOM - ((v - minV) / (maxV - minV || 1)) * (HEIGHT - PAD_TOP - PAD_BOTTOM);

  const linePath = clean.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t)},${y(p.v)}`).join(" ");
  const areaPath = `${linePath} L${x(clean[clean.length - 1].t)},${HEIGHT - PAD_BOTTOM} L${x(clean[0].t)},${HEIGHT - PAD_BOTTOM} Z`;

  const yTicks = 4;
  const tickValues = Array.from({ length: yTicks + 1 }, (_, i) => minV + ((maxV - minV) * i) / yTicks);

  const handleMove: React.MouseEventHandler<SVGSVGElement> = (event) => {
    const svg = containerRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const relX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    let nearest = 0;
    let best = Infinity;
    clean.forEach((p, i) => {
      const d = Math.abs(x(p.t) - relX);
      if (d < best) {
        best = d;
        nearest = i;
      }
    });
    setHoverIndex(nearest);
  };

  const hovered = hoverIndex !== null ? clean[hoverIndex] : null;

  return (
    <div className="relative">
      <svg
        ref={containerRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full"
        style={{ height: HEIGHT }}
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
        role="img"
        aria-label={`${seriesLabel} price over time`}
      >
        {tickValues.map((v, i) => (
          <g key={i}>
            <line
              x1={PAD_LEFT}
              x2={WIDTH - PAD_RIGHT}
              y1={y(v)}
              y2={y(v)}
              stroke="var(--grid-hairline)"
              strokeWidth={1}
            />
            <text x={PAD_LEFT - 8} y={y(v)} textAnchor="end" dominantBaseline="middle" className="fill-text-muted text-[10px] tabular-nums">
              {formatPrice(v)}
            </text>
          </g>
        ))}

        <path d={areaPath} fill="var(--series-1)" opacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {hovered && (
          <g>
            <line
              x1={x(hovered.t)}
              x2={x(hovered.t)}
              y1={PAD_TOP}
              y2={HEIGHT - PAD_BOTTOM}
              stroke="var(--baseline)"
              strokeWidth={1}
            />
            <circle cx={x(hovered.t)} cy={y(hovered.v)} r={5} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />
          </g>
        )}
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute top-1 rounded-md border border-border-hairline bg-surface-2 px-2.5 py-1.5 text-xs shadow-sm"
          style={{ left: `min(${(x(hovered.t) / WIDTH) * 100}%, calc(100% - 140px))` }}
        >
          <div className="text-text-muted">{new Date(hovered.t).toLocaleString()}</div>
          <div className="font-semibold tabular-nums text-text-primary">{formatPrice(hovered.v)}</div>
        </div>
      )}
    </div>
  );
}
