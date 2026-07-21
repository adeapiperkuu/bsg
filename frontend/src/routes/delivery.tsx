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
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import {
  Card,
  SectionGroupHeading,
  SectionHeader,
  KpiCard,
  StatusPill,
} from "@/components/bsg/widgets";
import { TablePagination } from "@/components/bsg/TablePagination";
import { usePagination } from "@/hooks/usePagination";
import {
  useDeliveryPortfolioQuery,
  useOrganisationsQuery,
  useProjectDailyActionsQuery,
  useProjectDeliveryConfidenceQuery,
  useProjectRootCausesQuery,
  useRootCauseTrendsQuery,
} from "@/lib/queries/delivery";
import {
  avgDailyThroughputUnits,
  computePortfolioKpis,
  hasSufficientData,
  resolveDefaultProjectId,
  riskTier,
  sortByPriority,
  toPortfolioEntries,
} from "@/features/delivery/portfolio";
import {
  buildOperationalTimeline,
  deriveActiveBottlenecks,
  deriveDeliveryInsights,
  deriveTrafficDistribution,
  milestoneHitRateFor,
  trafficLightLabel,
} from "@/features/delivery/insights";
import {
  DeliveryInsightsPanel,
  OperationalTimelinePanel,
  PortfolioHealthBar,
  TeamBottlenecksPanel,
} from "@/features/delivery/DashboardSections";
import { DeliveryRootCauseSection } from "@/features/delivery/root-cause";
import { OperationalBriefingPanel } from "@/features/delivery/briefing/OperationalBriefingPanel";
import { TodaysFocusPanel } from "@/features/delivery/pm-actions/TodaysFocusPanel";
import { flushNavPrefetch } from "@/lib/queries/nav-prefetch";
import { cn } from "@/lib/utils";
import { MitigationRecommendationsPanel } from "@/features/mitigation-recommendations/components/MitigationRecommendationsPanel";
import { DeliveryChat } from "@/components/delivery";
import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/delivery")({
  validateSearch: (search: Record<string, unknown>) => ({
    projectId: typeof search.projectId === "string" ? search.projectId : undefined,
  }),
  // Warm the cache but do NOT await — each section renders from its own query and
  // shows a placeholder until that query lands.
  //
  // Client-only: the API authenticates by cookie, which SSR has no jar for, so a
  // server-side warm would 401 and be discarded. nav-prefetch also keeps its
  // single-flight state in module globals, which on the server would be shared
  // across concurrent requests.
  loader: ({ context: { queryClient } }) => {
    if (typeof window === "undefined") return;
    flushNavPrefetch(queryClient, "/delivery");
  },
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
  // An absent tier means the score never computed, which is not the same as a medium
  // risk. StatusPill renders unmapped labels in neutral grey, so this reads as unknown
  // rather than as a real amber assessment.
  return "Unknown";
}

/** Rows per page for the Drill-Down Analytics table. */
const PROJECTS_PER_PAGE = 25;

function buildConfidenceChart(
  points: Array<{ created_at: string; score_pct: string; forecast_completion_date: string | null }>,
) {
  const sorted = [...points].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );

  if (sorted.length === 0) return [];

  const chart = sorted.map((point) => {
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

function DeliveryPage() {
  const navigate = useNavigate({ from: "/delivery" });
  const { projectId: urlProjectId } = Route.useSearch();
  const syncedProjectIdRef = useRef<string | null>(null);
  const userRole = useAuthStore((s) => s.user?.role);
  const isInternalUser = userRole !== "client";

  const organisationsQuery = useOrganisationsQuery();
  const portfolioQuery = useDeliveryPortfolioQuery();

  const organisations = useMemo(() => organisationsQuery.data ?? [], [organisationsQuery.data]);

  // One payload defines the whole page: table rows, selector options and KPIs. Rows used
  // to come from /projects (capped at 100) while KPIs came from the portfolio (up to
  // 200), so above 100 projects the KPIs counted projects the table never listed.
  const entries = useMemo(() => toPortfolioEntries(portfolioQuery.data), [portfolioQuery.data]);
  const rankedEntries = useMemo(() => sortByPriority(entries), [entries]);
  const projects = useMemo(() => rankedEntries.map((entry) => entry.project), [rankedEntries]);

  // total_count counts what the caller may see; entries is what the limit let through.
  const totalVisibleProjects = portfolioQuery.data?.total_count ?? entries.length;
  const truncatedCount = Math.max(0, totalVisibleProjects - entries.length);

  const resolvedProjectId = useMemo(
    () => resolveDefaultProjectId(rankedEntries, urlProjectId),
    [rankedEntries, urlProjectId],
  );

  useEffect(() => {
    if (!resolvedProjectId || resolvedProjectId === urlProjectId) return;
    if (syncedProjectIdRef.current === resolvedProjectId) return;
    syncedProjectIdRef.current = resolvedProjectId;
    navigate({ search: { projectId: resolvedProjectId }, replace: true });
  }, [resolvedProjectId, urlProjectId, navigate]);

  const confidenceQuery = useProjectDeliveryConfidenceQuery(resolvedProjectId);
  const rootCausesQuery = useProjectRootCausesQuery(resolvedProjectId);
  const rootCauseTrendsQuery = useRootCauseTrendsQuery(resolvedProjectId, isInternalUser);
  // Same query key as TodaysFocusPanel — React Query dedupes, so this costs no extra
  // request. The timeline reads completed-action history from it.
  const dailyActionsQuery = useProjectDailyActionsQuery(resolvedProjectId, isInternalUser);

  const orgById = useMemo(
    () => new Map(organisations.map((org) => [org.id, org.name])),
    [organisations],
  );

  const selectedEntry = rankedEntries.find((entry) => entry.project.id === resolvedProjectId);
  const selectedProject = selectedEntry?.project;
  const selectedDashboard = selectedEntry?.dashboard;
  const portfolioMilestones = useMemo(
    () => portfolioQuery.data?.milestones ?? [],
    [portfolioQuery.data?.milestones],
  );

  // Sections wait only on the queries they read; the project universe comes from the
  // portfolio, so the table and selector wait on it.
  const orgsLoading = organisationsQuery.isLoading;
  const portfolioLoading = portfolioQuery.isLoading;
  const confidenceLoading = portfolioLoading || confidenceQuery.isLoading;
  const rootCausesLoading = portfolioLoading || rootCausesQuery.isLoading;
  const rootCauseTrendsLoading = portfolioLoading || rootCauseTrendsQuery.isLoading;

  const errorMessage =
    (organisationsQuery.error instanceof Error ? organisationsQuery.error.message : null) ??
    (portfolioQuery.error instanceof Error ? portfolioQuery.error.message : null) ??
    (rootCausesQuery.error instanceof Error ? rootCausesQuery.error.message : null);

  // Computed from the full entry list, never the current page: pagination is a view
  // window over the same universe the KPIs summarise, so paging must not move them.
  const portfolioKpis = useMemo(
    () => computePortfolioKpis(entries, portfolioMilestones),
    [entries, portfolioMilestones],
  );
  const trafficDistribution = useMemo(() => deriveTrafficDistribution(entries), [entries]);
  const deliveryInsights = useMemo(
    () => deriveDeliveryInsights(entries, rootCauseTrendsQuery.data),
    [entries, rootCauseTrendsQuery.data],
  );
  const activeBottlenecks = useMemo(
    () => deriveActiveBottlenecks(selectedDashboard),
    [selectedDashboard],
  );
  const timelineEvents = useMemo(
    () => buildOperationalTimeline(selectedDashboard, dailyActionsQuery.data?.history ?? []),
    [selectedDashboard, dailyActionsQuery.data?.history],
  );

  const confidenceChart = buildConfidenceChart(confidenceQuery.data ?? []);

  const selectProject = (projectId: string) => {
    navigate({ search: { projectId } });
  };

  // Drill-down row expansion for the analytics table.
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(null);

  // Paginate the ranked list so the highest-priority projects occupy page 1. Reset to
  // page 1 only when the portfolio itself changes, not when the focused project does.
  const pagination = usePagination(rankedEntries, portfolioQuery.data, PROJECTS_PER_PAGE);

  if (errorMessage) {
    return (
      <Card>
        <SectionHeader title="Delivery Performance" sub="Unable to load delivery data" />
        <p className="text-sm text-[color:var(--danger)]">{errorMessage}</p>
      </Card>
    );
  }

  if (portfolioLoading || orgsLoading) {
    return <PageLoadingScreen />;
  }

  if (projects.length === 0) {
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
            disabled={projects.length === 0}
            className="rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none"
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Executive delivery overview                                         */}
        {/* ------------------------------------------------------------------ */}
        <div id="overview" className="space-y-4">
          <SectionGroupHeading title="Executive Delivery Overview" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {/* No delta on either card: the portfolio payload carries only current
                values, so there is no prior period to compare against. */}
            <KpiCard
              label="Throughput (7-day avg)"
              value={`${formatNumber(portfolioKpis.totalThroughput)}/d`}
              tone="success"
            />
            <KpiCard
              label="Schedule Confidence"
              value={`${portfolioKpis.avgConfidence}%`}
              tone="warning"
            />
            <KpiCard
              label="At-Risk Projects"
              value={portfolioKpis.atRiskProjects}
              tone="danger"
            />
            <KpiCard
              label="Milestone Hit Rate"
              value={
                portfolioKpis.milestoneHitRate === null
                  ? "—"
                  : `${portfolioKpis.milestoneHitRate}%`
              }
              tone="success"
            />
          </div>
          <PortfolioHealthBar distribution={trafficDistribution} />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Daily operational briefing (15.4)                                   */}
        {/* ------------------------------------------------------------------ */}
        <div id="briefing" className="space-y-4">
          <SectionGroupHeading title="Daily Operational Briefing" />
          <OperationalBriefingPanel
            projectId={resolvedProjectId}
            projectName={selectedProject?.name}
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Root-cause analysis (15.1/15.2)                                     */}
        {/* ------------------------------------------------------------------ */}
        <div id="root-cause" className="space-y-4">
          <SectionGroupHeading title="Root-Cause Analysis" />
          <DeliveryRootCauseSection
            projectName={selectedProject?.name}
            rootCauses={rootCausesQuery.data}
            trends={rootCauseTrendsQuery.data}
            loading={rootCausesLoading}
            trendsLoading={rootCauseTrendsLoading}
            fallbackConfidence={selectedDashboard?.confidence ?? null}
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* PM action planner (15.3) + mitigations                              */}
        {/* ------------------------------------------------------------------ */}
        <div id="actions" className="space-y-4">
          <SectionGroupHeading title="PM Action Planner" />
          <TodaysFocusPanel
            projectId={resolvedProjectId}
            projectName={selectedProject?.name}
          />
          <MitigationRecommendationsPanel projectId={resolvedProjectId} />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Confidence trends                                                   */}
        {/* ------------------------------------------------------------------ */}
        <div id="confidence" className="space-y-4">
          <SectionGroupHeading title="Confidence Trends" />
          <Card>
            <SectionHeader
              title="Confidence Trend & 4-Week Forecast"
              sub="Schedule confidence · historical + forecast"
            />
            {confidenceLoading ? (
              <div className="h-[240px] animate-pulse rounded bg-elevated" />
            ) : confidenceChart.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={confidenceChart}>
                  <CartesianGrid stroke="#2a2d3a" strokeDasharray="3 3" />
                  <XAxis dataKey="week" {...axis} />
                  {/* Full 0-100: a domain floored at 50 clipped the low-confidence
                      projects that most need looking at straight off the chart. */}
                  <YAxis {...axis} domain={[0, 100]} />
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
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Team bottlenecks                                                    */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-4">
          <SectionGroupHeading title="Team Bottlenecks" />
          <TeamBottlenecksPanel
            projectName={selectedProject?.name}
            bottlenecks={activeBottlenecks}
            loading={portfolioLoading}
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Operational timeline                                                */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-4">
          <SectionGroupHeading title="Operational Timeline" />
          <OperationalTimelinePanel
            projectName={selectedProject?.name}
            events={timelineEvents}
            loading={portfolioLoading || dailyActionsQuery.isLoading}
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Delivery insights                                                   */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-4">
          <SectionGroupHeading title="Delivery Insights" />
          <DeliveryInsightsPanel
            insights={deliveryInsights}
            loading={portfolioLoading || rootCauseTrendsLoading}
          />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Drill-down analytics                                                */}
        {/* ------------------------------------------------------------------ */}
        <div id="analytics" className="space-y-4">
          <SectionGroupHeading title="Drill-Down Analytics" />
          <Card>
            <SectionHeader
              title="Project Performance"
              sub={
                portfolioLoading
                  ? undefined
                  : `Ordered by attention needed · showing ${pagination.rangeStart}-${pagination.rangeEnd} of ${pagination.total}`
              }
            />
            {truncatedCount > 0 && (
              <p className="mb-3 rounded border border-[color:var(--warning)]/30 bg-[color:var(--warning)]/10 px-3 py-2 text-xs text-[color:var(--warning)]">
                Showing {entries.length} of {totalVisibleProjects} projects. The KPIs above cover
                only these {entries.length}; {truncatedCount} more are not included.
              </p>
            )}
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
                  {portfolioLoading
                    ? Array.from({ length: 3 }).map((_, index) => (
                        <tr key={index} className="border-b border-border/50">
                          <td colSpan={7} className="py-2.5">
                            <div className="h-4 animate-pulse rounded bg-elevated" />
                          </td>
                        </tr>
                      ))
                    : pagination.pageItems.map(({ project, dashboard }) => (
                        <Fragment key={project.id}>
                          <tr
                            className={cn(
                              "border-b border-border/50",
                              project.id === resolvedProjectId && "bg-elevated",
                            )}
                          >
                            <td className="py-2.5 pr-3 font-medium">{project.name}</td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {orgsLoading
                                ? "—"
                                : (orgById.get(project.org_id) ?? project.vertical)}
                            </td>
                            <td className="py-2.5 pr-3">
                              {`${formatNumber(avgDailyThroughputUnits(dashboard))}/d`}
                            </td>
                            <td className="py-2.5 pr-3">
                              {hasSufficientData(dashboard)
                                ? `${Math.round(dashboard.confidence)}%`
                                : "Insufficient data"}
                            </td>
                            <td className="py-2.5 pr-3">
                              <StatusPill status={riskLabel(riskTier(dashboard))} />
                            </td>
                            <td className="py-2.5 pr-3 text-muted-foreground">
                              {project.updated_at ? formatTimestamp(project.updated_at) : "—"}
                            </td>
                            <td className="py-2.5 pr-3">
                              <div className="flex gap-1.5">
                                <button
                                  onClick={() =>
                                    setExpandedProjectId(
                                      expandedProjectId === project.id ? null : project.id,
                                    )
                                  }
                                  className="rounded border border-border px-2 py-0.5 text-[11px]"
                                >
                                  {expandedProjectId === project.id ? "Hide" : "Details"}
                                </button>
                                <button
                                  onClick={() => selectProject(project.id)}
                                  className="rounded border border-border px-2 py-0.5 text-[11px]"
                                >
                                  Focus
                                </button>
                              </div>
                            </td>
                          </tr>
                          {expandedProjectId === project.id && (
                            <tr className="border-b border-border/50 bg-elevated/40">
                              <td colSpan={7} className="px-3 py-3">
                                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px] md:grid-cols-4">
                                  <div>
                                    <p className="uppercase tracking-wide text-muted-foreground">
                                      Traffic light
                                    </p>
                                    <StatusPill status={trafficLightLabel(dashboard)} />
                                  </div>
                                  <div>
                                    <p className="uppercase tracking-wide text-muted-foreground">
                                      Open risks
                                    </p>
                                    <p className="text-sm text-foreground">
                                      {(dashboard.risks ?? []).length}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="uppercase tracking-wide text-muted-foreground">
                                      Active bottlenecks
                                    </p>
                                    <p className="text-sm text-foreground">
                                      {deriveActiveBottlenecks(dashboard).length}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="uppercase tracking-wide text-muted-foreground">
                                      Milestone hit rate
                                    </p>
                                    <p className="text-sm text-foreground">
                                      {milestoneHitRateFor(dashboard)}
                                    </p>
                                  </div>
                                  {(dashboard.risks ?? []).length > 0 && (
                                    <div className="col-span-2 md:col-span-4">
                                      <p className="uppercase tracking-wide text-muted-foreground">
                                        Top risks
                                      </p>
                                      <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                                        {(dashboard.risks ?? []).slice(0, 3).map((raw, index) => {
                                          const risk = raw as Record<string, unknown>;
                                          return (
                                            <li key={String(risk.id ?? index)}>
                                              · {String(risk.title ?? "Untitled risk")} (
                                              {String(risk.risk_tier ?? "unknown")})
                                            </li>
                                          );
                                        })}
                                      </ul>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                </tbody>
              </table>
            </div>
            {!portfolioLoading && pagination.totalPages > 1 && (
              <TablePagination
                currentPage={pagination.currentPage}
                totalPages={pagination.totalPages}
                onPageChange={pagination.setPage}
              />
            )}
          </Card>
        </div>
      </div>

      <div className="lg:col-span-3">
        <DeliveryChat projectId={resolvedProjectId} />
      </div>
    </div>
  );
}
