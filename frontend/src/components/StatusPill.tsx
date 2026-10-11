"use client";

import { useI18n } from "@/lib/i18n";
import type { SourceStatus } from "@/lib/types";

const STATUS_META: Record<SourceStatus, { key: `status.${string}`; color: string; icon: string }> = {
  healthy: { key: "status.healthy", color: "var(--status-good)", icon: "●" },
  degraded: { key: "status.degraded", color: "var(--status-warning)", icon: "▲" },
  down: { key: "status.down", color: "var(--status-critical)", icon: "✕" },
  not_configured: { key: "status.not_configured", color: "var(--status-neutral)", icon: "○" },
  unknown: { key: "status.unknown", color: "var(--status-neutral)", icon: "○" },
};

export function StatusPill({ status }: { status: SourceStatus }) {
  const { t } = useI18n();
  const meta = STATUS_META[status] ?? STATUS_META.unknown;
  const label = t(meta.key as Parameters<typeof t>[0]);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-border-hairline px-2.5 py-1 text-xs font-medium text-text-secondary"
      title={label}
    >
      <span style={{ color: meta.color }} aria-hidden>
        {meta.icon}
      </span>
      {label}
    </span>
  );
}
