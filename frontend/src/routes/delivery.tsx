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

function formatRelativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function riskLabel(
  trafficLight: DeliveryDashboardResponse["traffic_light"],
  tier?: string,
): string {
  if (tier === "critical" || trafficLight === "red") return "Critical";
  if (tier === "high") return "High";
  if (tier === "medium" || trafficLight === "yellow") return "Medium";
  if (trafficLight === "green") return "Low";
  return "Medium";
}

function latestThroughputUnits(dashboard: DeliveryDashboardResponse | undefined): number {
  const overview = asRecord(dashboard?.overview);
  const latest = asRecord(overview?.latest_throughput);
  return typeof latest?.units_completed === "number" ? latest.units_completed : 0;
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

  const lastIndex = chart.length - 1;
  const lastScore = chart[lastIndex]?.confidence;
  if (lastScore != null && sorted[lastIndex]?.forecast_completion_date) {
    chart[lastIndex] = { ...chart[lastIndex], forecast: lastScore };
    for (let i = 1; i <= 4 && lastIndex + i < chart.length + 4; i += 1) {
      const forecastScore = Math.max(50, lastScore - i * 2);
      chart.push({
        week: `F${i}`,
        confidence: null,
        forecast: forecastScore,
      });
    }
  }

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

  const dashboards = useMemo(() => {
    if (!resolvedProjectId || !selectedDashboardQuery.data) {
      return portfolioDashboards;
    }
    return {
      ...portfolioDashboards,
      [resolvedProjectId]: selectedDashboardQuery.data,
    };
  }, [portfolioDashboards, resolvedProjectId, selectedDashboardQuery.data]);

  const selectedProject = projects.find((project) => project.id === resolvedProjectId);
  const selectedDashboard = resolvedProjectId ? dashboards[resolvedProjectId] : undefined;
  const portfolioMilestones = portfolioQuery.data?.milestones ?? [];

  const loading =
    projectsQuery.isLoading || organisationsQuery.isLoading || portfolioQuery.isLoading;
  const errorMessage =
    (projectsQuery.error instanceof Error ? projectsQuery.error.message : null) ??
    (organisationsQuery.error instanceof Error ? organisationsQuery.error.message : null) ??
    (portfolioQuery.error instanceof Error ? portfolioQuery.error.message : null);

  const portfolioKpis = useMemo(() => {
    const dashboardList = Object.values(dashboards);
    const totalThroughput = dashboardList.reduce(
      (sum, dashboard) => sum + latestThroughputUnits(dashboard),
      0,
    );
    const avgConfidence =
      dashboardList.length > 0
        ? dashboardList.reduce((sum, dashboard) => sum + dashboard.confidence, 0) /
          dashboardList.length
        : 0;
    const atRiskProjects = dashboardList.filter(
      (dashboard) => dashboard.traffic_light !== "green",
    ).length;
    const milestoneHitRate = computeMilestoneHitRate(portfolioMilestones);

    const confidenceValues = dashboardList.map((dashboard) => dashboard.confidence);
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
  }, [dashboards, portfolioMilestones]);

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
            label="Throughput"
            value={loading ? "ΓÇö" : `${formatNumber(portfolioKpis.totalThroughput)}/d`}
            delta={portfolioKpis.throughputDelta}
            tone="success"
          />
          <KpiCard
            label="Schedule Confidence"
            value={loading ? "ΓÇö" : `${portfolioKpis.avgConfidence}%`}
            delta={portfolioKpis.confidenceDelta}
            tone="warning"
          />
          <KpiCard
            label="At-Risk Projects"
            value={loading ? "ΓÇö" : portfolioKpis.atRiskProjects}
            tone="danger"
          />
          <KpiCard
            label="Milestone Hit Rate"
            value={
              loading || portfolioKpis.milestoneHitRate === null
                ? "ΓÇö"
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
            right={<AiBadge confidence={Math.round(selectedDashboard?.confidence ?? 0)} />}
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
                  ≡ƒôÄ {attachment}
                </span>
              ))}
            </div>
          )}
        </Card>

        <MitigationRecommendationsPanel projectId={resolvedProjectId} />

        <Card>
          <SectionHeader
            title="Confidence Trend & 4-Week Forecast"
            sub="Schedule confidence ┬╖ historical + forecast"
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
                  <th className="py-2 pr-3 font-medium">Throughput</th>
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
                      const dashboard = dashboards[project.id];
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
                            {formatNumber(latestThroughputUnits(dashboard))}/d
                          </td>
                          <td className="py-2.5 pr-3">
                            {dashboard ? `${Math.round(dashboard.confidence)}%` : "ΓÇö"}
                          </td>
                          <td className="py-2.5 pr-3">
                            {dashboard ? (
                              <StatusPill
                                status={riskLabel(dashboard.traffic_light, tier)}
                              />
                            ) : (
                              "ΓÇö"
                            )}
                          </td>
                          <td className="py-2.5 pr-3 text-muted-foreground">
                            {formatRelativeTime(project.updated_at)}
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
