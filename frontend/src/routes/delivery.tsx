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
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Card,
  SectionHeader,
  KpiCard,
  AiBadge,
  EvidenceBadge,
  StatusPill,
} from "@/components/bsg/widgets";
import {
  type DeliveryDashboardResponse,
  type ProjectRead,
  type ThroughputSnapshotRead,
} from "@/lib/api";
import {
  useDeliveryDashboardQuery,
  useDeliveryPortfolioQuery,
  useOrganisationsQuery,
  useProjectDeliveryConfidenceQuery,
  useProjectThroughputQuery,
  useProjectsQuery,
} from "@/lib/queries/delivery";

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

type Msg = { role: "ai" | "user"; text: string; sources?: string[] };

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

function priorityLabel(tier: string): string {
  if (tier === "critical" || tier === "high") return "High";
  if (tier === "medium") return "Medium";
  return "Low";
}

function latestThroughputUnits(dashboard: DeliveryDashboardResponse | undefined): number {
  const overview = asRecord(dashboard?.overview);
  const latest = asRecord(overview?.latest_throughput);
  return typeof latest?.units_completed === "number" ? latest.units_completed : 0;
}

function throughputDelta(snapshots: ThroughputSnapshotRead[]): string | undefined {
  if (snapshots.length < 2) return undefined;
  const current = snapshots[0];
  const previous = snapshots[1];
  if (previous.units_completed === 0) return undefined;
  const pct =
    ((current.units_completed - previous.units_completed) / previous.units_completed) * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}% WoW`;
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

function buildRecommendations(dashboard: DeliveryDashboardResponse) {
  const riskItems = dashboard.risks.map((risk) => {
    const tier = String(risk.risk_tier ?? "medium");
    const slippage = risk.slippage_probability;
    const confidence =
      typeof slippage === "number"
        ? Math.round(slippage)
        : typeof slippage === "string"
          ? Math.round(parseFloat(slippage))
          : Math.round(dashboard.confidence);
    return {
      id: String(risk.id ?? risk.title),
      title: String(risk.title ?? "Risk mitigation"),
      priority: priorityLabel(tier),
      confidence: Number.isFinite(confidence) ? confidence : Math.round(dashboard.confidence),
    };
  });

  const bottleneckItems = dashboard.bottlenecks.map((bottleneck) => ({
    id: String(bottleneck.id ?? bottleneck.title),
    title: String(bottleneck.title ?? "Resolve bottleneck"),
    priority: "Medium",
    confidence: Math.round(dashboard.confidence),
  }));

  return [...riskItems, ...bottleneckItems].slice(0, 3);
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

function buildAgentAnswer(
  question: string,
  project: ProjectRead | undefined,
  dashboard: DeliveryDashboardResponse | undefined,
  atRiskCount: number,
  throughputSnapshots: ThroughputSnapshotRead[],
): string {
  const q = question.toLowerCase();
  const projectName = project?.name ?? "the selected project";

  if (q.includes("risk") || q.includes("blocking")) {
    const openRisks = dashboard?.risks ?? [];
    if (openRisks.length === 0) {
      return `${atRiskCount} project(s) are flagged at portfolio level. ${projectName} has no open delivery risks right now.`;
    }
    const titles = openRisks
      .slice(0, 3)
      .map((risk) => String(risk.title ?? "Untitled risk"))
      .join("; ");
    return `${atRiskCount} project(s) are at risk in the portfolio. For ${projectName}, open risks include: ${titles}.`;
  }

  if (q.includes("throughput") || q.includes("decline")) {
    const units = latestThroughputUnits(dashboard);
    const delta = throughputDelta(throughputSnapshots);
    return `${projectName} is reporting ${formatNumber(units)}/d throughput${delta ? ` (${delta})` : ""} with ${Math.round(dashboard?.confidence ?? 0)}% schedule confidence.`;
  }

  if (dashboard?.daily_summary) return dashboard.daily_summary;

  return `${projectName} is at ${Math.round(dashboard?.confidence ?? 0)}% schedule confidence with traffic-light status ${dashboard?.traffic_light ?? "unknown"}.`;
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
  const throughputQuery = useProjectThroughputQuery(resolvedProjectId);

  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");

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
  const throughputSnapshots = throughputQuery.data ?? [];
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
  const recommendations = selectedDashboard ? buildRecommendations(selectedDashboard) : [];
  const confidenceChart = buildConfidenceChart(confidenceQuery.data ?? []);
  const evidenceAttachments = selectedDashboard
    ? [
        ...selectedDashboard.risks.map((risk) => String(risk.title ?? "")),
        ...selectedDashboard.bottlenecks.map((bottleneck) => String(bottleneck.title ?? "")),
      ].filter(Boolean)
    : [];

  const atRiskCount = portfolioKpis.atRiskProjects;

  useEffect(() => {
    if (!selectedDashboard || !selectedProject) return;
    const initialText =
      selectedDashboard.daily_summary ??
      buildAgentAnswer(
        "portfolio status",
        selectedProject,
        selectedDashboard,
        atRiskCount,
        throughputSnapshots,
      );
    setMessages([{ role: "ai", text: initialText }]);
  }, [
    selectedProject?.id,
    selectedDashboard?.daily_summary,
    selectedDashboard?.confidence,
    selectedDashboard?.traffic_light,
    atRiskCount,
  ]);

  const selectProject = (projectId: string) => {
    navigate({ search: { projectId } });
  };

  const send = (question: string) => {
    const answer = buildAgentAnswer(
      question,
      selectedProject,
      selectedDashboard,
      portfolioKpis.atRiskProjects,
      throughputSnapshots,
    );
    const sources = evidenceAttachments.slice(0, 2).map((title) => title);
    setMessages((current) => [
      ...current,
      { role: "user", text: question },
      { role: "ai", text: answer, sources },
    ]);
    setInput("");
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
                  📎 {attachment}
                </span>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <SectionHeader title="Mitigation Recommendations" right={<EvidenceBadge />} />
          {loading ? (
            <div className="h-16 animate-pulse rounded-md bg-elevated" />
          ) : recommendations.length > 0 ? (
            <div className="space-y-2">
              {recommendations.map((recommendation) => (
                <div
                  key={recommendation.id}
                  className="rounded-md border border-border bg-elevated p-3"
                >
                  <div className="flex items-center gap-2">
                    <StatusPill status={recommendation.priority} />
                    <AiBadge confidence={recommendation.confidence} />
                  </div>
                  <div className="mt-1.5 text-sm">{recommendation.title}</div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <select className="rounded border border-border bg-card px-2 py-1 text-[11px]">
                      <option>Owner: Unassigned</option>
                    </select>
                    <div className="flex gap-1.5">
                      <button className="rounded bg-[color:var(--brand)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--brand-foreground)]">
                        Accept
                      </button>
                      <button className="rounded border border-border px-2.5 py-1 text-[11px]">
                        Reject
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No mitigation recommendations available.</p>
          )}
        </Card>

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
                            {dashboard ? `${Math.round(dashboard.confidence)}%` : "—"}
                          </td>
                          <td className="py-2.5 pr-3">
                            {dashboard ? (
                              <StatusPill
                                status={riskLabel(dashboard.traffic_light, tier)}
                              />
                            ) : (
                              "—"
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
        <Card className="sticky top-20">
          <SectionHeader
            title="Ask Delivery Agent"
            sub="Evidence-backed answers"
            right={<AiBadge />}
          />
          <div className="mb-3 flex flex-wrap gap-1.5">
            {[
              "Which projects are at risk?",
              "Why did throughput decline?",
              "What's blocking delivery?",
            ].map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => send(suggestion)}
                className="rounded-full border border-border bg-elevated px-2.5 py-1 text-[11px] hover:bg-card"
              >
                {suggestion}
              </button>
            ))}
          </div>
          <div className="mb-3 max-h-[420px] space-y-2 overflow-y-auto">
            {messages.map((message, index) => (
              <div
                key={index}
                className={
                  message.role === "ai"
                    ? "rounded-md border border-border bg-elevated p-2.5 text-xs"
                    : "rounded-md bg-[color:var(--brand)]/10 p-2.5 text-xs"
                }
              >
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {message.role === "ai" ? "Delivery Agent" : "You"}
                </div>
                <div>{message.text}</div>
                {message.role === "ai" && message.sources && message.sources.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {message.sources.map((source) => (
                      <span
                        key={source}
                        className="rounded border border-border bg-card px-1.5 py-0.5 text-[9px]"
                      >
                        📎 {source}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (input.trim()) send(input.trim());
            }}
            className="flex gap-2"
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask about delivery…"
              className="flex-1 rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none focus:border-[color:var(--brand)]"
            />
            <button
              type="submit"
              className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]"
            >
              Send
            </button>
          </form>
        </Card>
      </div>
    </div>
  );
}
