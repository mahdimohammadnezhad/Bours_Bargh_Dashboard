"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { SourceHealthPanel } from "@/components/SourceHealthPanel";
import { api } from "@/lib/api";
import { formatClockTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { CollectorLog, SourceHealth } from "@/lib/types";

export default function DataHealthPage() {
  const { t } = useI18n();
  const [sources, setSources] = useState<SourceHealth[]>([]);
  const [logs, setLogs] = useState<CollectorLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  const STATUS_LOG_COLOR: Record<CollectorLog["status"], string> = {
    success: "text-[var(--status-good)]",
    error: "text-[var(--status-critical)]",
    skipped: "text-[var(--status-warning)]",
    not_configured: "text-text-muted",
  };
  const STATUS_LOG_LABEL: Record<CollectorLog["status"], string> = {
    success: t("health.status.success"),
    error: t("health.status.error"),
    skipped: t("health.status.skipped"),
    not_configured: t("health.status.not_configured"),
  };

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      Promise.all([api.sourceHealth(), api.collectorLogs(undefined, 100)])
        .then(([s, l]) => {
          if (cancelled) return;
          setSources(s);
          setLogs(l);
          setError(null);
        })
        .catch((err) => !cancelled && setError(String(err)));
    };
    load();
    const id = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const statusCounts = logs.reduce<Record<string, number>>((acc, log) => {
    const key = log.http_status ? String(log.http_status) : log.status;
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold text-text-primary">{t("health.title")}</h1>
        <p className="text-sm text-text-muted">
          {t("health.subtitle_pre")}{" "}
          <code className="ltr-content rounded bg-surface-1 px-1 py-0.5 text-xs">docs/DATA_SOURCES.md</code>{" "}
          {t("health.subtitle_post")}
        </p>
      </div>

      {error && <EmptyState title={t("health.unreachable.title")} detail={error} />}

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("health.sources")}</h2>
        <SourceHealthPanel sources={sources} />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("health.httpDist")}</h2>
        {Object.keys(statusCounts).length === 0 ? (
          <EmptyState title={t("health.noCycles.title")} />
        ) : (
          <div className="flex flex-wrap gap-2">
            {Object.entries(statusCounts).map(([status, count]) => (
              <span key={status} className="ltr-content rounded-md border border-border-hairline bg-surface-1 px-2.5 py-1 text-xs tabular-nums text-text-secondary">
                {status}: <span className="font-semibold text-text-primary">{count}</span>
              </span>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-text-primary">{t("health.recentCycles")}</h2>
        {logs.length === 0 ? (
          <EmptyState title={t("health.noCycles.title")} detail={t("health.noCycles.detail")} />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-hairline">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border-hairline bg-surface-1 text-start text-xs text-text-muted">
                  <th className="px-3 py-2 text-start font-medium">{t("health.col.time")}</th>
                  <th className="px-3 py-2 text-start font-medium">{t("health.col.source")}</th>
                  <th className="px-3 py-2 text-start font-medium">{t("health.col.status")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("health.col.http")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("health.col.latency")}</th>
                  <th className="px-3 py-2 text-end font-medium">{t("health.col.fetchedInsertedSkipped")}</th>
                  <th className="px-3 py-2 text-start font-medium">{t("health.col.error")}</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log, i) => (
                  <tr key={i} className="border-b border-border-hairline last:border-0">
                    <td className="px-3 py-2 tabular-nums text-text-muted">{formatClockTime(log.started_at)}</td>
                    <td className="ltr-content px-3 py-2 text-start text-text-secondary">{log.source_id}</td>
                    <td className={`px-3 py-2 font-medium ${STATUS_LOG_COLOR[log.status]}`}>{STATUS_LOG_LABEL[log.status]}</td>
                    <td className="px-3 py-2 text-end tabular-nums text-text-secondary">{log.http_status ?? "—"}</td>
                    <td className="px-3 py-2 text-end tabular-nums text-text-secondary">
                      {log.latency_ms ? `${Math.round(log.latency_ms)}ms` : "—"}
                    </td>
                    <td className="px-3 py-2 text-end tabular-nums text-text-secondary">
                      {log.records_fetched}/{log.records_inserted}/{log.records_skipped}
                    </td>
                    <td className="ltr-content max-w-xs truncate px-3 py-2 text-start text-xs text-[var(--status-critical)]">{log.error_message ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
