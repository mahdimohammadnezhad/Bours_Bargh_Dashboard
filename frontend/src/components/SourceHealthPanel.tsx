"use client";

import { useEffect, useState } from "react";
import { formatRelativeTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { SourceHealth } from "@/lib/types";
import { StatusPill } from "./StatusPill";

export function SourceHealthPanel({ sources }: { sources: SourceHealth[] }) {
  const [now, setNow] = useState(() => Date.now());
  const { t } = useI18n();

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="divide-y divide-border-hairline rounded-lg border border-border-hairline">
      {sources.map((s) => (
        <div key={s.source_id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          {/* min-w-0 + max-w-full: a long error URL truncates to the space
              available instead of forcing the whole page wider than the screen. */}
          <div className="min-w-0">
            <div className="ltr-content text-sm font-medium text-text-primary">{s.name}</div>
            <div className="text-xs text-text-muted">
              {t("sourceHealth.lastSuccess")} {formatRelativeTime(s.last_success_at, now, t)}
              {s.latency_ms !== null && <span className="ltr-content"> · {Math.round(s.latency_ms)}ms</span>}
              {s.consecutive_failures > 0 && ` · ${s.consecutive_failures} ${t("sourceHealth.consecutiveFailures")}`}
            </div>
            {s.last_error && (
              <div className="ltr-content mt-0.5 max-w-full truncate text-xs text-[var(--status-critical)]" title={s.last_error}>
                {s.last_error}
              </div>
            )}
          </div>
          <StatusPill status={s.status} />
        </div>
      ))}
    </div>
  );
}
