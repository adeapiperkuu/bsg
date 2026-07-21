export function WorkforcePlaceholder({
  title,
  reason,
  actionLabel,
  onAction,
}: {
  title: string;
  reason: string;
  /** When both are provided, the empty state becomes an actionable setup task (CTA). */
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="flex flex-col items-center rounded-md border border-dashed border-border bg-elevated/50 px-3 py-3 text-center">
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{reason}</p>
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="mt-3 rounded border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 px-3 py-1.5 text-[11px] font-medium text-[color:var(--brand)] transition-colors hover:bg-[color:var(--brand)]/20"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
