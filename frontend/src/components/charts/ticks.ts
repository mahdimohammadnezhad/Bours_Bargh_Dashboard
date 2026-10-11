/** Round tick step (1, 2, 2.5 or 5 x 10^k) giving about `count` intervals. */
export function niceStep(span: number, count = 4): number {
  const raw = Math.abs(span) / count || 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? 10 * magnitude;
}

/** Round ticks covering [min, max]; the first/last tick is the axis domain. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  const step = niceStep(max - min || Math.abs(max) || 1, count);
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks.length >= 2 ? ticks : [start, start + step];
}

/** Ticks symmetric around zero, for diverging values. */
export function symmetricTicks(maxAbs: number): number[] {
  const step = niceStep(maxAbs, 2);
  const n = Math.max(1, Math.ceil(maxAbs / step));
  return Array.from({ length: 2 * n + 1 }, (_, i) => Number(((i - n) * step).toFixed(10)));
}
