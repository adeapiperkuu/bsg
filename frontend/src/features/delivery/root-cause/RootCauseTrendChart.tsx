import type { RootCauseTrendFactorRead } from "@/lib/api";

type Props = {
  factors: RootCauseTrendFactorRead[];
  loading?: boolean;
};

export function RootCauseTrendChart({ factors, loading = false }: Props) {
  if (loading) {
    return <div className="h-28 animate-pulse rounded bg-elevated" />;
  }
  const rows = factors.filter(
    (factor) => (factor.today ?? 0) > 0 || (factor.last_week ?? 0) > 0 || (factor.last_month ?? 0) > 0,
  );
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No root-cause trend history yet. Recalculate after scoring to populate snapshots.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {rows.slice(0, 6).map((factor) => (
        <div
          key={factor.factor}
          className="grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-3 text-xs"
        >
          <span className="truncate">{factor.label}</span>
          <span className="tabular-nums text-muted-foreground">
            T {factor.today == null ? "—" : `${Math.round(factor.today)}%`}
          </span>
          <span className="tabular-nums text-muted-foreground">
            W {factor.last_week == null ? "—" : `${Math.round(factor.last_week)}%`}
          </span>
          <span className="tabular-nums text-muted-foreground">
            M {factor.last_month == null ? "—" : `${Math.round(factor.last_month)}%`}
          </span>
          <span className="uppercase text-muted-foreground">{factor.trend_direction}</span>
        </div>
      ))}
    </div>
  );
}
