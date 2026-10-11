export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border-hairline px-6 py-10 text-center">
      <p className="text-sm font-medium text-text-secondary">{title}</p>
      {detail && <p className="max-w-md text-xs text-text-muted">{detail}</p>}
    </div>
  );
}
