import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  LineChart,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { useEffect, useMemo, useRef } from "react";
import {
  Card,
  SectionHeader,
  KpiCard,
  AiBadge,
  StatusPill,
} from "@/components/bsg/widgets";
import {
  type DeliveryDashboardResponse,
} from "@/lib/api";
import {
  useDeliveryDashboardQuery,
  useDeliveryPortfolioQuery,
  useOrganisationsQuery,
  useProjectDeliveryConfidenceQuery,
  useProjectsQuery,
} from "@/lib/queries/delivery";
import { MitigationRecommendationsPanel } from "@/features/mitigation-recommendations/components/MitigationRecommendationsPanel";
import { DeliveryChat } from "@/components/delivery";

export const Route = createFileRoute("/delivery")({
  validateSearch: (search: Record<string, unknown>) => ({
    projectId: typeof search.projectId === "string" ? search.projectId : undefined,
  }),
  component: DeliveryPage,
});

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

const ROOT_CAUSE_LABELS: Record<string, string> = {
  confidence_shortfall: "Schedule confidence shortfall",
  throughput_decline: "Throughput decline",
  milestone_urgency: "Milestone urgency",
  open_bottlenecks: "Open bottlenecks",
  quality_drift: "Quality drift",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatNumber(value: number): string {
  return value.toLocaleString();
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function riskLabel(tier?: string): string {
  if (tier === "critical") return "Critical";
  if (tier === "high") return "High";
  if (tier === "medium") return "Medium";
  if (tier === "low") return "Low";
  return "Medium";
}

function hasSufficientData(dashboard: DeliveryDashboardResponse | undefined): boolean {
  const overview = asRecord(dashboard?.overview);
  return overview?.has_sufficient_data !== false;
}

function avgDailyThroughputUnits(dashboard: DeliveryDashboardResponse | undefined): number {
  const overview = asRecord(dashboard?.overview);
  const latest = asRecord(overview?.latest_throughput);
  return typeof latest?.rolling_7day_units === "number"
    ? Math.round(latest.rolling_7day_units / 7)
    : 0;
}

function buildRootCauses(dashboard: DeliveryDashboardResponse) {
  const overview = asRecord(dashboard.overview);
  const calculatedRisk = asRecord(overview?.calculated_risk);
  const causes = asRecord(calculatedRisk?.contributing_causes) ?? {};
  const entries = Object.entries(causes)
    .map(([key, value]) => ({
      cause: ROOT_CAUSE_LABELS[key] ?? key.replace(/_/g, " "),
      impact: typeof value === "number" ? value : 0,
    }))
    .filter((item) => item.impact > 0)
    .sort((a, b) => b.impact - a.impact);

  const total = entries.reduce((sum, item) => sum + item.impact, 0) || 1;
  return entries.map((item) => ({
    cause: item.cause,
    impact: Math.round((item.impact / total) * 100),
  }));
}

function buildConfidenceChart(
  points: Array<{ created_at: string; score_pct: string; forecast_completion_date: string | null }>,
) {
  const sorted = [...points].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  if (sorted.length === 0) return [];

  const chart = sorted.map((point, index) => {
    const date = new Date(point.created_at);
    const week = `W${Math.ceil(
      (date.getTime() - new Date(date.getFullYear(), 0, 1).getTime()) / 604_800_000,
    )}`;
    const score = parseFloat(point.score_pct);
    return {
      week: `${week}`,
      confidence: Number.isFinite(score) ? Math.round(score) : null,
      forecast: null as number | null,
    };
  });

  return chart;
}

function computeMilestoneHitRate(milestones: Array<Record<string, unknown>>): number | null {
  const closed = milestones.filter(
    (milestone) => milestone.status === "completed" || milestone.status === "missed",
  );
  if (closed.length === 0) return null;
  const hit = closed.filter((milestone) => milestone.status === "completed").length;
  return Math.round((hit / closed.length) * 100);
}

function DeliveryPage() {
  const navigate = useNavigate({ from: "/delivery" });
  const { projectId: urlProjectId } = Route.useSearch();
  const syncedProjectIdRef = useRef<string | null>(null);

  const projectsQuery = useProjectsQuery();
  const organisationsQuery = useOrganisationsQuery();
  const portfolioQuery = useDeliveryPortfolioQuery();

  const projects = projectsQuery.data ?? [];
  const organisations = organisationsQuery.data ?? [];

  const resolvedProjectId = useMemo(() => {
    if (projects.length === 0) return null;
    if (urlProjectId && projects.some((project) => project.id === urlProjectId)) {
      return urlProjectId;
    }
    return projects[0]?.id ?? null;
  }, [projects, urlProjectId]);

  useEffect(() => {
    if (!resolvedProjectId || resolvedProjectId === urlProjectId) return;
    if (syncedProjectIdRef.current === resolvedProjectId) return;
    syncedProjectIdRef.current = resolvedProjectId;
    navigate({ search: { projectId: resolvedProjectId }, replace: true });
  }, [resolvedProjectId, urlProjectId, navigate]);

  const selectedDashboardQuery = useDeliveryDashboardQuery(resolvedProjectId);
  const confidenceQuery = useProjectDeliveryConfidenceQuery(resolvedProjectId);

  const orgById = useMemo(
    () => new Map(organisations.map((org) => [org.id, org.name])),
    [organisations],
  );

  const portfolioDashboards = useMemo(() => {
    if (!portfolioQuery.data) return {};
    return Object.fromEntries(
      portfolioQuery.data.projects.map((entry) => [entry.project_id, entry.dashboard]),
    );
  }, [portfolioQuery.data]);

  const selectedProject = projects.find((project) => project.id === resolvedProjectId);
  const selectedDashboard = resolvedProjectId
    ? selectedDashboardQuery.data ?? portfolioDashboards[resolvedProjectId]
    : undefined;
  const portfolioMilestones = useMemo(
    () => (portfolioQuery.data?.projects ?? []).flatMap((entry) => entry.dashboard.milestones),
    [portfolioQuery.data],
  );

  const loading =
    projectsQuery.isLoading || organisationsQuery.isLoading || portfolioQuery.isLoading;
  const errorMessage =
    (projectsQuery.error instanceof Error ? projectsQuery.error.message : null) ??
    (organisationsQuery.error instanceof Error ? organisationsQuery.error.message : null) ??
    (portfolioQuery.error instanceof Error ? portfolioQuery.error.message : null);

  const portfolioKpis = useMemo(() => {
    const dashboardList = Object.values(portfolioDashboards);
    const scoredDashboards = dashboardList.filter((dashboard) => hasSufficientData(dashboard));
    const totalThroughput = dashboardList.reduce(
      (sum, dashboard) => sum + avgDailyThroughputUnits(dashboard),
      0,
    );
    const avgConfidence =
      scoredDashboards.length > 0
        ? scoredDashboards.reduce((sum, dashboard) => sum + dashboard.confidence, 0) /
          scoredDashboards.length
        : 0;
    const atRiskProjects = scoredDashboards.filter(
      (dashboard) => dashboard.traffic_light !== "green",
    ).length;
    const milestoneHitRate = computeMilestoneHitRate(portfolioMilestones);

    const confidenceValues = scoredDashboards.map((dashboard) => dashboard.confidence);
    const confidenceDelta =
      confidenceValues.length >= 2
        ? `${(confidenceValues[confidenceValues.length - 1] - confidenceValues[0]).toFixed(1)} pts`
        : undefined;

    return {
      totalThroughput,
      avgConfidence: Math.round(avgConfidence),
      atRiskProjects,
      milestoneHitRate,
      throughputDelta: undefined,
      confidenceDelta,
    };
  }, [portfolioDashboards, portfolioMilestones]);

  const rootCauses = selectedDashboard ? buildRootCauses(selectedDashboard) : [];
  const confidenceChart = buildConfidenceChart(confidenceQuery.data ?? []);
  const evidenceAttachments = selectedDashboard
    ? [
        ...selectedDashboard.risks.map((risk) => String(risk.title ?? "")),
        ...selectedDashboard.bottlenecks.map((bottleneck) => String(bottleneck.title ?? "")),
      ].filter(Boolean)
    : [];

  const selectProject = (projectId: string) => {
    navigate({ search: { projectId } });
  };

  if (errorMessage) {
    return (
      <Card>
        <SectionHeader title="Delivery Performance" sub="Unable to load delivery data" />
        <p className="text-sm text-[color:var(--danger)]">{errorMessage}</p>
      </Card>
    );
  }

  if (!loading && projects.length === 0) {
    return (
      <Card>
        <SectionHeader title="Delivery Performance" sub="No projects available" />
        <p className="text-sm text-muted-foreground">
          No projects are available for the current user.
        </p>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-10">
      <div className="space-y-5 lg:col-span-7">
        <div className="flex items-center justify-end gap-2">
          <span className="text-xs text-muted-foreground">Project focus</span>
          <select
            value={resolvedProjectId ?? ""}
            onChange={(event) => selectProject(event.target.value)}
            disabled={loading || projects.length === 0}
            className="rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none"
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <KpiCard
            label="Throughput (7-day avg)"
            value={loading ? "—" : `${formatNumber(portfolioKpis.totalThroughput)}/d`}
            delta={portfolioKpis.throughputDelta}
            tone="success"
          />
          <KpiCard
            label="Schedule Confidence"
            value={loading ? "—" : `${portfolioKpis.avgConfidence}%`}
            delta={portfolioKpis.confidenceDelta}
            tone="warning"
          />
          <KpiCard
            label="At-Risk Projects"
            value={loading ? "—" : portfolioKpis.atRiskProjects}
            tone="danger"
          />
          <KpiCard
            label="Milestone Hit Rate"
            value={
              loading || portfolioKpis.milestoneHitRate === null
                ? "—"
                : `${portfolioKpis.milestoneHitRate}%`
            }
            tone="success"
          />
        </div>

        <Card>
          <SectionHeader
            title="Root Cause Analysis"
            sub={
              selectedProject
                ? `Why is ${selectedProject.name} at risk?`
                : "Root cause breakdown"
            }
            right={
              selectedDashboard && !hasSufficientData(selectedDashboard) ? (
                <AiBadge label="Insufficient data" source="formula" />
              ) : (
                <AiBadge
                  label="Risk score"
                  source="formula"
                  confidence={Math.round(selectedDashboard?.confidence ?? 0)}
                />
              )
            }
          />
          {loading ? (
            <div className="h-2 overflow-hidden rounded bg-elevated">
              <div className="h-full w-1/3 animate-pulse rounded bg-[color:var(--brand)]" />
            </div>
          ) : rootCauses.length > 0 ? (
            <div className="space-y-2.5">
              {rootCauses.map((cause) => (
                <div key={cause.cause}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span>{cause.cause}</span>
                    <span className="text-muted-foreground">{cause.impact}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded bg-elevated">
                    <div
                      className="h-full rounded bg-[color:var(--brand)]"
                      style={{ width: `${cause.impact * 2}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No contributing causes identified.</p>
          )}
          {evidenceAttachments.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5 text-[10px]">
              {evidenceAttachments.slice(0, 3).map((attachment) => (
                <span
                  key={attachment}
                  className="rounded border border-border bg-elevated px-2 py-0.5 text-muted-foreground"
                >
                  📄 {attachment}
                </span>
              ))}
            </div>
          )}
        </Card>

        <MitigationRecommendationsPanel projectId={resolvedProjectId} />

        <Card>
          <SectionHeader
            title="Confidence Trend & 4-Week Forecast"
            sub="Schedule confidence · historical + forecast"
          />
          {loading ? (
            <div className="h-[240px] animate-pulse rounded bg-elevated" />
          ) : confidenceChart.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={confidenceChart}>
                <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
                <XAxis dataKey="week" {...axis} />
                <YAxis {...axis} domain={[50, 100]} />
                <Tooltip contentStyle={tip} />
                <Line
                  dataKey="confidence"
                  stroke="#00c9a7"
                  strokeWidth={2}
                  dot={false}
                  name="Confidence"
                  connectNulls={false}
                />
                <Line
                  dataKey="forecast"
                  stroke="#00c9a7"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  dot={false}
                  name="Forecast"
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-muted-foreground">No confidence history available yet.</p>
          )}
        </Card>

        <Card>
          <SectionHeader title="Project Performance" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">Project</th>
                  <th className="py-2 pr-3 font-medium">Client</th>
                  <th className="py-2 pr-3 font-medium">Throughput (7d avg)</th>
                  <th className="py-2 pr-3 font-medium">Confidence</th>
                  <th className="py-2 pr-3 font-medium">Risk</th>
                  <th className="py-2 pr-3 font-medium">Updated</th>
                  <th className="py-2 pr-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {loading
                  ? Array.from({ length: 3 }).map((_, index) => (
                      <tr key={index} className="border-b border-border/50">
                        <td colSpan={7} className="py-2.5">
                          <div className="h-4 animate-pulse rounded bg-elevated" />
                        </td>
                      </tr>
                    ))
                  : projects.map((project) => {
                      const dashboard = portfolioDashboards[project.id];
                      const overview = asRecord(dashboard?.overview);
                      const calculatedRisk = asRecord(overview?.calculated_risk);
                      const tier =
                        typeof calculatedRisk?.tier === "string" ? calculatedRisk.tier : undefined;
                      return (
                        <tr key={project.id} className="border-b border-border/50">
                          <td className="py-2.5 pr-3 font-medium">{project.name}</td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {orgById.get(project.org_id) ?? project.vertical}
                          </td>
                          <td className="py-2.5 pr-3">
                            {formatNumber(avgDailyThroughputUnits(dashboard))}/d
                          </td>
                          <td className="py-2.5 pr-3">
                            {!dashboard
                              ? "—"
                              : hasSufficientData(dashboard)
                                ? `${Math.round(dashboard.confidence)}%`
                                : "Insufficient data"}
                          </td>
                          <td className="py-2.5 pr-3">
                            {dashboard ? (
                              <StatusPill
                                status={
                                  hasSufficientData(dashboard)
                                    ? riskLabel(tier)
                                    : "Insufficient data"
                                }
                              />
                            ) : (
                              "—"
                            )}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {formatTimestamp(project.updated_at)}
                          </td>
                          <td className="py-2.5 pr-3">
                            <button
                              onClick={() => selectProject(project.id)}
                              className="rounded border border-border px-2 py-0.5 text-[11px]"
                            >
                              Open
                            </button>
                          </td>
                        </tr>
                      );
                    })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="lg:col-span-3">
        <DeliveryChat projectId={resolvedProjectId} />
      </div>
    </div>
  );
}
