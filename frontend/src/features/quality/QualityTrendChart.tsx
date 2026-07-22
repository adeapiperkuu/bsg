import { KpiTrendChart } from "@/components/bsg/time-series";
import { useKpiSeriesQuery } from "@/lib/queries/time-series";
import type { QualityDashboard as QualityDashboardData } from "@/lib/api";

function domainFallback(trend: QualityDashboardData["trend"]) {
  return trend.map((t) => ({
    label: `W${t.iso_week}`,
    goldAccuracy: t.gold_set_accuracy_pct != null ? Number(t.gold_set_accuracy_pct) : null,
    iaa: t.iaa_krippendorff_alpha != null ? Number(t.iaa_krippendorff_alpha) : null,
  }));
}

export function QualityTrendChart({
  trend,
  projectId,
}: {
  trend: QualityDashboardData["trend"];
  projectId?: string | null;
}) {
  const goldSeries = useKpiSeriesQuery("quality.gold_set_accuracy", {
    project_id: projectId ?? undefined,
    interval: "week",
  });
  const iaaSeries = useKpiSeriesQuery("quality.iaa", {
    project_id: projectId ?? undefined,
    interval: "week",
  });

  const persistedEnough =
    (goldSeries.data?.points.length ?? 0) >= 2 || (iaaSeries.data?.points.length ?? 0) >= 2;

  let data = domainFallback(trend);
  if (persistedEnough) {
    const byLabel = new Map<string, { label: string; goldAccuracy: number | null; iaa: number | null }>();
    for (const point of goldSeries.data?.points ?? []) {
      const label = point.bucket_start.slice(0, 10);
      byLabel.set(label, {
        label,
        goldAccuracy: point.numeric_value == null ? null : Number(point.numeric_value),
        iaa: null,
      });
    }
    for (const point of iaaSeries.data?.points ?? []) {
      const label = point.bucket_start.slice(0, 10);
      const existing = byLabel.get(label) ?? { label, goldAccuracy: null, iaa: null };
      existing.iaa = point.numeric_value == null ? null : Number(point.numeric_value);
      byLabel.set(label, existing);
    }
    data = [...byLabel.values()].sort((a, b) => a.label.localeCompare(b.label));
  }

  return (
    <KpiTrendChart
      title="Quality Trend"
      sub={
        persistedEnough
          ? "Gold accuracy & IAA · persisted time-series"
          : "Gold accuracy & IAA · up to 6 weeks (domain fallback)"
      }
      data={data}
      series={[
        { dataKey: "goldAccuracy", name: "Gold Accuracy %", yAxisId: "l" },
        { dataKey: "iaa", name: "IAA", yAxisId: "r", color: "#3b82f6" },
      ]}
      leftDomain={[80, 100]}
      rightDomain={[0.75, 0.95]}
      loading={Boolean(projectId) && (goldSeries.isLoading || iaaSeries.isLoading) && !persistedEnough && trend.length === 0}
      error={goldSeries.error ?? iaaSeries.error}
      emptyMessage="No quality trend history yet."
    />
  );
}
