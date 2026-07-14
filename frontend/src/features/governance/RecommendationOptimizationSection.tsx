import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Card, KpiCard, SectionHeader } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  generateRecommendationOptimizationReport,
  recommendationOptimizationCompareQueryOptions,
  recommendationOptimizationSummaryQueryOptions,
} from "@/lib/queries/governance";
import type { GovernanceEffectivenessFilters } from "@/types/governance";

function metricValue(metrics: Record<string, unknown> | undefined, key: string): string {
  const raw = metrics?.[key];
  if (raw == null) return "—";
  if (typeof raw === "number") return String(raw);
  if (typeof raw === "object" && raw !== null && "value" in raw) {
    const value = (raw as { value: number | null }).value;
    return value == null ? "—" : `${value}%`;
  }
  return String(raw);
}

export function RecommendationOptimizationSection({
  filters,
  enabled = true,
}: {
  filters: GovernanceEffectivenessFilters;
  enabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [strategyA, setStrategyA] = useState<string>("");
  const [strategyB, setStrategyB] = useState<string>("");

  const summaryQuery = useQuery({
    ...recommendationOptimizationSummaryQueryOptions(filters),
    enabled,
  });

  const strategies = summaryQuery.data?.strategy_versions ?? [];
  const compareA = strategyA || strategies[0]?.strategy_version || "";
  const compareB =
    strategyB ||
    strategies.find((s) => s.strategy_version !== compareA)?.strategy_version ||
    "";

  const compareQuery = useQuery({
    ...recommendationOptimizationCompareQueryOptions(compareA, compareB, filters.days ?? 30),
    enabled: enabled && Boolean(compareA && compareB && compareA !== compareB),
  });

  const reportMutation = useMutation({
    mutationFn: (period: "weekly" | "monthly" | "quarterly") =>
      generateRecommendationOptimizationReport(period),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["governance", "optimization"] });
    },
  });

  const strategyOptions = useMemo(
    () => strategies.map((s) => s.strategy_version),
    [strategies],
  );

  if (!enabled) return null;

  const summary = summaryQuery.data;
  const drift = summary?.drift_warnings ?? [];
  const pending = summary?.pending_approvals ?? [];
  const activeRules = summary?.active_learning_rules ?? [];
  const shadows = summary?.recent_shadow_evaluations ?? [];
  const reports = summary?.recent_reports ?? [];

  return (
    <section className="space-y-4" aria-label="Recommendation optimization">
      <SectionHeader
        title="Recommendation Optimization"
        sub="Controlled learning rules, shadow evaluation, drift, and strategy versions"
      />

      {summaryQuery.isLoading ? (
        <div className="grid gap-3 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : summaryQuery.isError ? (
        <Card className="p-4 text-sm text-destructive">
          Unable to load optimization summary. Leadership access is required.
        </Card>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <KpiCard
              label="Active rules"
              value={String(activeRules.length)}
              hint={summary?.learning_rules_enabled ? "Flag enabled" : "Flag disabled"}
            />
            <KpiCard label="Pending approvals" value={String(pending.length)} />
            <KpiCard label="Drift warnings" value={String(drift.length)} />
            <KpiCard
              label="Acceptance"
              value={metricValue(summary?.metrics, "acceptance_rate")}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="space-y-3 p-4">
              <h3 className="text-sm font-semibold">Learning rules</h3>
              {activeRules.length === 0 && pending.length === 0 ? (
                <p className="text-sm text-muted-foreground">No learning rules yet.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {[...activeRules, ...pending].slice(0, 8).map((rule) => (
                    <li key={rule.id} className="flex items-center justify-between gap-2">
                      <span>
                        {rule.rule_type} · v{rule.version}
                      </span>
                      <span className="text-muted-foreground">{rule.status}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-xs text-muted-foreground">
                Rules require approval and shadow evaluation before activation. Rollback is
                audited; no automatic governance actions.
              </p>
            </Card>

            <Card className="space-y-3 p-4">
              <h3 className="text-sm font-semibold">Drift warnings</h3>
              {drift.length === 0 ? (
                <p className="text-sm text-muted-foreground">No drift alerts in this window.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {drift.slice(0, 6).map((alert, index) => (
                    <li key={alert.id ?? `${alert.alert_type}-${index}`}>
                      <span className="font-medium uppercase tracking-wide text-xs text-muted-foreground">
                        {alert.severity}
                      </span>
                      <div>{alert.message}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="space-y-3 p-4">
              <h3 className="text-sm font-semibold">Shadow evaluations</h3>
              {shadows.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No shadow runs yet. Production rankings stay unchanged in shadow mode.
                </p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {shadows.map((shadow) => (
                    <li key={shadow.id} className="flex justify-between gap-2">
                      <span>
                        Sample {shadow.sample_size} · rank changes{" "}
                        {String(
                          (shadow.expected_impact as { rank_changes?: number }).rank_changes ??
                            "—",
                        )}
                      </span>
                      <span className="text-muted-foreground">{shadow.status}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card className="space-y-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">Strategy versions</h3>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={reportMutation.isPending}
                    onClick={() => reportMutation.mutate("weekly")}
                  >
                    Weekly report
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={reportMutation.isPending}
                    onClick={() => reportMutation.mutate("monthly")}
                  >
                    Monthly
                  </Button>
                </div>
              </div>
              {strategies.length === 0 ? (
                <p className="text-sm text-muted-foreground">No strategy versions registered.</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {strategies.map((strategy) => (
                    <li key={strategy.id} className="flex justify-between gap-2">
                      <span>
                        {strategy.strategy_version}
                        {strategy.is_active ? " (active)" : ""}
                      </span>
                      <span className="text-muted-foreground">
                        q={strategy.quality_version} · exp={strategy.explanation_version}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {reports.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Latest report: {reports[0].period} ({reports[0].period_start} →{" "}
                  {reports[0].period_end})
                </p>
              )}
            </Card>
          </div>

          <Card className="space-y-3 p-4">
            <h3 className="text-sm font-semibold">Strategy comparison</h3>
            <div className="flex flex-wrap gap-2">
              <label className="text-sm">
                A{" "}
                <select
                  className="ml-1 rounded border bg-background px-2 py-1"
                  value={compareA}
                  onChange={(e) => setStrategyA(e.target.value)}
                >
                  {strategyOptions.map((version) => (
                    <option key={version} value={version}>
                      {version}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm">
                B{" "}
                <select
                  className="ml-1 rounded border bg-background px-2 py-1"
                  value={compareB}
                  onChange={(e) => setStrategyB(e.target.value)}
                >
                  {strategyOptions.map((version) => (
                    <option key={version} value={version}>
                      {version}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {compareQuery.isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : compareQuery.data ? (
              <div className="grid gap-2 text-sm md:grid-cols-3">
                <div>
                  Acceptance Δ: {compareQuery.data.deltas.acceptance_rate ?? "—"}
                </div>
                <div>
                  Conversion Δ: {compareQuery.data.deltas.conversion_rate ?? "—"}
                </div>
                <div>
                  FP Δ: {compareQuery.data.deltas.false_positive_rate ?? "—"}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Select two different strategy versions to compare.
              </p>
            )}
          </Card>
        </>
      )}
    </section>
  );
}
