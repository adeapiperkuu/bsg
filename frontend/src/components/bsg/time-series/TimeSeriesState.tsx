import type { ReactNode } from "react";

export function TimeSeriesState({
  loading,
  error,
  empty,
  emptyMessage = "No time-series history yet.",
  children,
}: {
  loading?: boolean;
  error?: unknown;
  empty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <div
        className="flex h-[200px] items-center justify-center text-sm text-muted-foreground"
        role="status"
        aria-live="polite"
      >
        Loading time-series…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="flex h-[200px] items-center justify-center text-sm text-[color:var(--danger)]"
        role="alert"
      >
        Unable to load time-series data.
      </div>
    );
  }
  if (empty) {
    return (
      <div
        className="flex h-[200px] items-center justify-center text-sm text-muted-foreground"
        role="status"
      >
        {emptyMessage}
      </div>
    );
  }
  return <>{children}</>;
}
