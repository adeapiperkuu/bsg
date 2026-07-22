import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import type { KpiTrendSummary } from "@/types/time-series";

function fmt(value: number | string | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toFixed(2);
}

function favorabilityStatus(
  value: KpiTrendSummary["semantic_favorability"],
): "On Track" | "Warning" | "Critical" {
  if (value === "improving" || value === "on_target" || value === "stable") return "On Track";
  if (value === "declining" || value === "off_target") return "Warning";
  return "Critical";
}

export function KpiChangeSummary({
  title = "KPI Change",
  trend,
  loading,
}: {
  title?: string;
  trend: KpiTrendSummary | null | undefined;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <Card>
        <SectionHeader title={title} sub="Loading…" />
      </Card>
    );
  }
  if (!trend) {
    return (
      <Card>
        <SectionHeader title={title} sub="No trend summary available" />
      </Card>
    );
  }
  return (
    <Card>
      <SectionHeader
        title={title}
        sub={`${trend.observation_count} observations · ${trend.trend_direction_policy}`}
        right={<StatusPill status={favorabilityStatus(trend.semantic_favorability)} />}
      />
      <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4" aria-live="polite">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Latest</div>
          <div className="font-semibold">{fmt(trend.latest?.numeric_value)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Δ Absolute</div>
          <div className="font-semibold">{fmt(trend.absolute_change)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Δ %</div>
          <div className="font-semibold">{fmt(trend.percentage_change)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Favorability</div>
          <div className="font-semibold capitalize">{trend.semantic_favorability.replaceAll("_", " ")}</div>
        </div>
      </div>
    </Card>
  );
}
