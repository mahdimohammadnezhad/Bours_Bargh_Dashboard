interface StatTileProps {
  label: string;
  value: string;
  delta?: string | null;
  deltaDirection?: "up" | "down" | "flat";
  unit?: string;
}

export function StatTile({ label, value, delta, deltaDirection = "flat", unit }: StatTileProps) {
  const deltaColor =
    deltaDirection === "up"
      ? "text-[var(--delta-up-good)]"
      : deltaDirection === "down"
        ? "text-[var(--delta-down-bad)]"
        : "text-text-muted";

  return (
    <div className="rounded-lg border border-border-hairline bg-surface-1 px-4 py-3">
      <div className="text-xs font-medium text-text-secondary">{label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold text-text-primary">{value}</span>
        {unit && <span className="text-sm text-text-muted">{unit}</span>}
      </div>
      {delta && <div className={`mt-1 text-xs font-medium ${deltaColor}`}>{delta}</div>}
    </div>
  );
}
