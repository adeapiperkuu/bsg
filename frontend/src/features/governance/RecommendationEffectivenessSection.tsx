import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, KpiCard, SectionHeader } from "@/components/bsg/widgets";
import { Skeleton } from "@/components/ui/skeleton";
import { CHART_AXIS_STYLE, CHART_TOOLTIP_STYLE } from "@/features/quality/format";
import {
  frequentlyAcceptedCategoriesQueryOptions,
  frequentlyDismissedCategoriesQueryOptions,
  recommendationEffectivenessFunnelQueryOptions,
  recommendationEffectivenessSummaryQueryOptions,
  recommendationEffectivenessTrendsQueryOptions,
} from "@/lib/queries/governance";
import type { GovernanceEffectivenessFilters, GovernanceEffectivenessMetric } from "@/types/governance";

function formatRate(metric?: GovernanceEffectivenessMetric | null): string {
  if (!metric || metric.value == null) return "—";
  return `${metric.value}%`;
}

function formatSeconds(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 3600) return `${Math.round(value / 60)}m`;
  return `${(value / 3600).toFixed(1)}h`;
}

export function RecommendationEffectivenessSection({
  filters,
  enabled = true,
}: {
  filters: GovernanceEffectivenessFilters;
  enabled?: boolean;
}) {
  const summaryQuery = useQuery({
    ...recommendationEffectivenessSummaryQueryOptions(filters),
    enabled,
  });
  const funnelQuery = useQuery({
    ...recommendationEffectivenessFunnelQueryOptions(filters),
    enabled: enabled && summaryQuery.isSuccess,
  });
  const trendsQuery = useQuery({
    ...recommendationEffectivenessTrendsQueryOptions(filters),
    enabled: enabled && summaryQuery.isSuccess,
  });
  const dismissedQuery = useQuery({
    ...frequentlyDismissedCategoriesQueryOptions(filters),
    enabled: enabled && summaryQuery.isSuccess,
  });
  const acceptedQuery = useQuery({
    ...frequentlyAcceptedCategoriesQueryOptions(filters),
    enabled: enabled && summaryQuery.isSuccess,
  });

  const summary = summaryQuery.data;
  const funnel = funnelQuery.data;
  const trends = trendsQuery.data?.points ?? [];
  const funnelChart = funnel
    ? [
        { stage: "Created", value: funnel.created },
        { stage: "Reviewed", value: funnel.reviewed },
        { stage: "Accepted", value: funnel.accepted },
        { stage: "Converted", value: funnel.converted },
        { stage: "Resolved", value: funnel.resolved },
      ]
    : [];

  return (
    <section className="space-y-4" aria-label="Recommendation effectiveness">
      <SectionHeader
        title="Recommendation Effectiveness"
        sub="Acceptance, conversion, resolution, quality, and category performance"
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
        {summaryQuery.isLoading && !summary ? (
          Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-24 w-full" />
          ))
        ) : (
          <>
            <KpiCard label="Total" value={summary?.total_recommendations ?? 0} />
            <KpiCard label="Reviewed" value={summary?.reviewed ?? 0} />
            <KpiCard label="Pending" value={summary?.pending ?? 0} />
            <KpiCard label="Acceptance" value={formatRate(summary?.acceptance_rate)} />
            <KpiCard label="Dismissal" value={formatRate(summary?.dismissal_rate)} />
            <KpiCard label="Conversion" value={formatRate(summary?.conversion_rate)} />
            <KpiCard label="Resolution" value={formatRate(summary?.resolution_rate)} />
            <KpiCard label="False Positive" value={formatRate(summary?.false_positive_rate)} />
            <KpiCard
              label="Avg Quality"
              value={summary?.average_quality_score ?? "—"}
            />
            <KpiCard
              label="Median Review"
              value={formatSeconds(summary?.median_time_to_review_seconds)}
            />
            <KpiCard
              label="Median Convert"
              value={formatSeconds(summary?.median_time_to_convert_seconds)}
            />
            <KpiCard
              label="Median Resolve"
              value={formatSeconds(summary?.median_time_to_resolve_seconds)}
            />
          </>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <SectionHeader title="Lifecycle Funnel" sub="Created → resolved" />
          {funnelQuery.isLoading && funnelChart.length === 0 ? (
            <Skeleton className="h-[240px] w-full" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={funnelChart}>
                <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
                <XAxis dataKey="stage" {...CHART_AXIS_STYLE} />
                <YAxis {...CHART_AXIS_STYLE} allowDecimals={false} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                <Bar dataKey="value" fill="#0D1240" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
        <Card>
          <SectionHeader title="Acceptance & Conversion Trends" sub="Daily volumes" />
          {trendsQuery.isLoading && trends.length === 0 ? (
            <Skeleton className="h-[240px] w-full" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart
                data={trends.map((point) => ({
                  date: point.date.slice(5),
                  accepted: point.accepted,
                  dismissed: point.dismissed,
                  converted: point.converted,
                  resolved: point.resolved,
                  false_positives: point.false_positives,
                }))}
              >
                <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
                <XAxis dataKey="date" {...CHART_AXIS_STYLE} />
                <YAxis {...CHART_AXIS_STYLE} allowDecimals={false} />
                <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 11, color: "#8b92a5" }} />
                <Line dataKey="accepted" stroke="#22c55e" strokeWidth={2} dot={false} />
                <Line dataKey="dismissed" stroke="#a3a3a3" strokeWidth={2} dot={false} />
                <Line dataKey="converted" stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line dataKey="resolved" stroke="#0D1240" strokeWidth={2} dot={false} />
                <Line dataKey="false_positives" stroke="#ef4444" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <SectionHeader
            title="Frequently Dismissed Categories"
            sub="Min sample enforced · not acceptance alone"
          />
          {(dismissedQuery.data ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No frequently dismissed categories meet the sample threshold.
            </p>
          ) : (
            <div className="space-y-2">
              {(dismissedQuery.data ?? []).slice(0, 6).map((row) => (
                <div
                  key={row.category_key}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-elevated px-3 py-2 text-xs"
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">
                      {row.trigger_type} · {row.vertical}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      n={row.sample_size} · dismiss {formatRate(row.dismissal_rate)} · FP{" "}
                      {formatRate(row.false_positive_rate)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card>
          <SectionHeader
            title="Frequently Accepted Categories"
            sub="Requires conversion + resolution + low FP"
          />
          {(acceptedQuery.data ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No successful accepted categories meet the sample threshold.
            </p>
          ) : (
            <div className="space-y-2">
              {(acceptedQuery.data ?? []).slice(0, 6).map((row) => (
                <div
                  key={row.category_key}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-elevated px-3 py-2 text-xs"
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">
                      {row.trigger_type} · {row.vertical}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      n={row.sample_size} · accept {formatRate(row.acceptance_rate)} · convert{" "}
                      {formatRate(row.conversion_rate)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </section>
  );
}
