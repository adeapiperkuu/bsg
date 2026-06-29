import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { useState } from "react";
import { Card, SectionHeader, KpiCard, AiBadge, EvidenceBadge, StatusPill } from "@/components/bsg/widgets";
import { AgentQueryBox } from "@/components/bsg/AgentQueryBox";
import {
  ERROR_CATEGORY_LABELS,
  fetchCalibrationBrief,
  fetchQualityDashboard,
  fetchReviewerScorecards,
  fetchSopAmbiguityFlags,
  listProjects,
  resolveRiskAlert,
} from "@/lib/api";

export const Route = createFileRoute("/quality")({ component: QualityPage });

const axis = {
  tick: { fill: "#8b92a5", fontSize: 11 },
  axisLine: { stroke: "#2a2d3a" },
  tickLine: { stroke: "#2a2d3a" },
};
const tip = {
  backgroundColor: "#20242f",
  border: "1px solid #2a2d3a",
  borderRadius: 8,
  fontSize: 12,
  color: "#f0f2f7",
};

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Number(v).toFixed(1)}%`;
}

function fmtIaa(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toFixed(2);
}

function kpiTone(
  value: number | null | undefined,
  kind: "accuracy" | "iaa" | "rework" | "alerts",
): "success" | "warning" | "danger" {
  if (value == null) return "warning";
  if (kind === "accuracy") return value >= 96 ? "success" : value >= 94 ? "warning" : "danger";
  if (kind === "iaa") return value >= 0.9 ? "success" : value >= 0.85 ? "warning" : "danger";
  if (kind === "rework") return value <= 3 ? "success" : value <= 5 ? "warning" : "danger";
  return value === 0 ? "success" : value <= 2 ? "warning" : "danger";
}

function QualityPage() {
  const queryClient = useQueryClient();
  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const [projectId, setProjectId] = useState<string | undefined>(undefined);
  const activeProjectId = projectId ?? projects[0]?.id;

  const { data: dashboard, isLoading, isError } = useQuery({
    queryKey: ["quality-dashboard", activeProjectId],
    queryFn: () => fetchQualityDashboard(activeProjectId!),
    enabled: Boolean(activeProjectId),
  });

  const { data: calibrationBrief } = useQuery({
    queryKey: ["calibration-brief", activeProjectId],
    queryFn: () => fetchCalibrationBrief(activeProjectId!),
    enabled: Boolean(activeProjectId),
  });

  const { data: sopFlags = [] } = useQuery({
    queryKey: ["sop-flags", activeProjectId],
    queryFn: () => fetchSopAmbiguityFlags(activeProjectId!),
    enabled: Boolean(activeProjectId),
  });

  const { data: reviewerScorecards = [] } = useQuery({
    queryKey: ["reviewer-scorecards", activeProjectId],
    queryFn: () => fetchReviewerScorecards(activeProjectId!),
    enabled: Boolean(activeProjectId),
  });

  const handleResolveAlert = async (alertId: string) => {
    await resolveRiskAlert(alertId, "Resolved from Quality dashboard");
    await queryClient.invalidateQueries({ queryKey: ["quality-dashboard", activeProjectId] });
  };

  const trendData =
    dashboard?.trend.map((t) => ({
      week: `W${t.iso_week}`,
      goldAccuracy: t.gold_set_accuracy_pct != null ? Number(t.gold_set_accuracy_pct) : null,
      iaa: t.iaa_krippendorff_alpha != null ? Number(t.iaa_krippendorff_alpha) : null,
    })) ?? [];

  const errorCategories =
    dashboard?.error_breakdown.map((e) => ({
      cat: ERROR_CATEGORY_LABELS[e.error_category] ?? e.error_category,
      count: Number(e.share_pct),
    })) ?? [];

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-muted-foreground">Project</label>
          <select
            className="rounded border border-border bg-card px-2 py-1.5 text-xs"
            value={activeProjectId ?? ""}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      </Card>

      {isLoading && <p className="text-sm text-muted-foreground">Loading quality dashboard…</p>}
      {isError && <p className="text-sm text-[color:var(--danger)]">Failed to load quality data.</p>}

      {dashboard && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <KpiCard
              label="Gold-Set Accuracy"
              value={fmtPct(dashboard.kpis.gold_set_accuracy_pct)}
              tone={kpiTone(dashboard.kpis.gold_set_accuracy_pct, "accuracy")}
            />
            <KpiCard
              label="IAA (Krippendorff α)"
              value={fmtIaa(dashboard.kpis.iaa_krippendorff_alpha)}
              tone={kpiTone(dashboard.kpis.iaa_krippendorff_alpha, "iaa")}
            />
            <KpiCard
              label="Rework Rate"
              value={fmtPct(dashboard.kpis.rework_rate_pct)}
              delta={
                dashboard.kpis.rework_rate_target_pct != null && dashboard.kpis.rework_rate_pct != null
                  ? `target ≤${Number(dashboard.kpis.rework_rate_target_pct).toFixed(1)}%`
                  : undefined
              }
              tone={kpiTone(dashboard.kpis.rework_rate_pct, "rework")}
            />
            <KpiCard
              label="Active Drift Alerts"
              value={String(dashboard.kpis.active_drift_alerts)}
              tone={kpiTone(dashboard.kpis.active_drift_alerts, "alerts")}
            />
          </div>

          <Card>
            <SectionHeader title="Quality Trend" sub="Gold accuracy & IAA · up to 6 weeks" />
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={trendData}>
                <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
                <XAxis dataKey="week" {...axis} />
                <YAxis yAxisId="l" {...axis} domain={[80, 100]} />
                <YAxis yAxisId="r" orientation="right" {...axis} domain={[0.75, 0.95]} />
                <Tooltip contentStyle={tip} />
                <Legend wrapperStyle={{ fontSize: 11, color: "#8b92a5" }} />
                <Line
                  yAxisId="l"
                  dataKey="goldAccuracy"
                  stroke="#0D1240"
                  strokeWidth={2}
                  name="Gold Accuracy %"
                  connectNulls
                />
                <Line yAxisId="r" dataKey="iaa" stroke="#3b82f6" strokeWidth={2} name="IAA" connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <Card>
              <SectionHeader title="Error Category Breakdown" sub="Current week share %" />
              {errorCategories.length > 0 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={errorCategories} layout="vertical" margin={{ left: 20 }}>
                    <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" {...axis} />
                    <YAxis dataKey="cat" type="category" {...axis} width={140} />
                    <Tooltip contentStyle={tip} />
                    <Bar dataKey="count" fill="#0D1240" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-muted-foreground">No error taxonomy data for the current week.</p>
              )}
            </Card>

            <Card>
              <SectionHeader title="Drift Alerts" sub="Linked AI actions" right={<AiBadge confidence={89} />} />
              <ul className="space-y-2">
                {dashboard.drift_alerts.length === 0 && (
                  <li className="text-xs text-muted-foreground">No active drift alerts.</li>
                )}
                {dashboard.drift_alerts.map((alert) => (
                  <li key={alert.id} className="rounded-md border border-border bg-elevated p-3 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <StatusPill status={alert.risk_tier === "critical" ? "Critical" : "Warning"} />
                        <span className="font-medium">{alert.title}</span>
                      </div>
                      {(alert.status === "open" || alert.status === "acknowledged") && (
                        <button
                          type="button"
                          onClick={() => handleResolveAlert(alert.id)}
                          className="rounded border border-border px-2 py-0.5 text-[10px] hover:bg-card"
                        >
                          Resolve
                        </button>
                      )}
                    </div>
                    <div className="mt-1 text-muted-foreground">{alert.detail}</div>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <Card>
            <SectionHeader title="Team Quality Scorecard" />
            {dashboard.data_gap_teams && dashboard.data_gap_teams.length > 0 && (
              <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-400">
                <span>⚠</span>
                <span>
                  {dashboard.data_gap_teams.length} team{dashboard.data_gap_teams.length !== 1 ? "s" : ""} below
                  minimum sample size (&lt;30 evaluated items):{" "}
                  <span className="font-medium">{dashboard.data_gap_teams.join(", ")}</span>
                </span>
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="py-2 pr-3 font-medium">Team</th>
                    <th className="py-2 pr-3 font-medium">Gold Acc</th>
                    <th className="py-2 pr-3 font-medium">IAA</th>
                    <th className="py-2 pr-3 font-medium">Rework</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {dashboard.team_scorecard.map((t) => (
                    <tr key={t.team_id} className="border-b border-border/50">
                      <td className="py-2.5 pr-3 font-medium">
                        {t.team_name}
                        {t.has_data_gap && (
                          <span className="ml-2 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
                            Data gap
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3">{fmtPct(t.gold_set_accuracy_pct)}</td>
                      <td className="py-2.5 pr-3">{fmtIaa(t.iaa_krippendorff_alpha)}</td>
                      <td className="py-2.5 pr-3">{fmtPct(t.rework_rate_pct)}</td>
                      <td className="py-2.5 pr-3">
                        <StatusPill status={t.status as "On Track" | "Warning" | "Critical"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {calibrationBrief && calibrationBrief.candidates.length > 0 && (
            <Card>
              <SectionHeader title="Calibration Brief" sub="UC-03 reviewer calibration candidates" right={<AiBadge />} />
              {calibrationBrief.brief_text && (
                <p className="mb-3 text-sm text-foreground/90">{calibrationBrief.brief_text}</p>
              )}
              <ul className="space-y-2 text-xs">
                {calibrationBrief.candidates.map((c) => (
                  <li key={c.annotator_id} className="rounded border border-border bg-elevated p-2">
                    <div className="flex items-center gap-2">
                      <StatusPill status={c.priority === "immediate" ? "Critical" : "Warning"} />
                      <span className="font-medium">Reviewer {c.annotator_id.slice(0, 8)}…</span>
                      <span className="text-muted-foreground">{c.accuracy_pct?.toFixed(1)}% · {c.items_evaluated} items</span>
                    </div>
                    <div className="mt-1 text-muted-foreground">{c.reason}</div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {sopFlags.length > 0 && (
            <Card>
              <SectionHeader title="SOP Ambiguity Flags" sub="UC-04 distributed IAA drop" />
              <ul className="space-y-2 text-xs">
                {sopFlags.map((f, i) => (
                  <li key={f.alert_id ?? i} className="rounded border border-border bg-elevated p-3">
                    <div className="font-medium">
                      {f.sop_version ? `SOP v${f.sop_version}` : "SOP ambiguity"} · {f.affected_reviewer_count} pairs
                    </div>
                    <div className="mt-1 text-muted-foreground">{f.detail}</div>
                    {f.draft_amendment && <p className="mt-2 text-foreground/90">{f.draft_amendment}</p>}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {reviewerScorecards.length > 0 && (
            <Card>
              <SectionHeader title="Reviewer Scorecards" sub="Per-reviewer weekly accuracy" />
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-left text-muted-foreground">
                    <tr className="border-b border-border">
                      <th className="py-2 pr-3 font-medium">Reviewer</th>
                      <th className="py-2 pr-3 font-medium">Week</th>
                      <th className="py-2 pr-3 font-medium">Items</th>
                      <th className="py-2 pr-3 font-medium">Accuracy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reviewerScorecards.map((r) => (
                      <tr key={r.id} className="border-b border-border/50">
                        <td className="py-2 pr-3 font-mono">{r.annotator_id.slice(0, 8)}…</td>
                        <td className="py-2 pr-3">W{r.iso_week}/{r.iso_year}</td>
                        <td className="py-2 pr-3">{r.items_evaluated}</td>
                        <td className="py-2 pr-3">{r.accuracy_pct != null ? `${r.accuracy_pct}%` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {dashboard.narrative && (
            <Card>
              <SectionHeader
                title="AI Quality Narrative"
                sub="Client-safe summary"
                right={
                  <div className="flex gap-2">
                    <AiBadge confidence={90} />
                    <EvidenceBadge />
                  </div>
                }
              />
              <p className="text-sm leading-6 text-foreground/90">{dashboard.narrative}</p>
            </Card>
          )}

          <Card>
            <SectionHeader title="Quality Agent" sub="Natural language queries" />
            <AgentQueryBox projectId={activeProjectId} />
          </Card>
        </>
      )}
    </div>
  );
}
