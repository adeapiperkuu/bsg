/**
 * Portfolio derivation for the Delivery Performance page.
 *
 * The page reads its entire project universe from `/delivery/portfolio` and nothing
 * else. It used to render rows from `/projects?limit=100` while computing KPIs from the
 * portfolio's up-to-200 dashboards, so a Delivery Manager above 100 projects saw KPIs
 * that counted projects absent from the table. Deriving both from one payload makes the
 * universe identical by construction rather than by convention.
 */
import type { DeliveryDashboardResponse, DeliveryPortfolioResponse } from "@/lib/api";

/** Project fields carried inside `dashboard.overview.project`. */
export type PortfolioProject = {
  id: string;
  org_id: string;
  name: string;
  vertical: string;
  status: string;
  target_end_date: string;
  updated_at: string | null;
  daily_target_units: number | null;
};

export type PortfolioEntry = {
  project: PortfolioProject;
  dashboard: DeliveryDashboardResponse;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function hasSufficientData(dashboard: DeliveryDashboardResponse | undefined): boolean {
  const overview = asRecord(dashboard?.overview);
  return overview?.has_sufficient_data !== false;
}

export function avgDailyThroughputUnits(dashboard: DeliveryDashboardResponse | undefined): number {
  const overview = asRecord(dashboard?.overview);
  const latest = asRecord(overview?.latest_throughput);
  return typeof latest?.rolling_7day_units === "number"
    ? Math.round(latest.rolling_7day_units / 7)
    : 0;
}

export function riskTier(dashboard: DeliveryDashboardResponse | undefined): string | undefined {
  const overview = asRecord(dashboard?.overview);
  const calculatedRisk = asRecord(overview?.calculated_risk);
  return typeof calculatedRisk?.tier === "string" ? calculatedRisk.tier : undefined;
}

/** Read the project record embedded in a dashboard's overview. */
function projectFromDashboard(
  projectId: string,
  dashboard: DeliveryDashboardResponse,
): PortfolioProject | null {
  const overview = asRecord(dashboard.overview);
  const project = asRecord(overview?.project);
  if (!project) return null;
  return {
    id: str(project.id) || projectId,
    org_id: str(project.org_id),
    name: str(project.name),
    vertical: str(project.vertical),
    status: str(project.status),
    target_end_date: str(project.target_end_date),
    updated_at: typeof project.updated_at === "string" ? project.updated_at : null,
    daily_target_units:
      typeof project.daily_target_units === "number" ? project.daily_target_units : null,
  };
}

/** Flatten the portfolio payload into one project-plus-dashboard list. */
export function toPortfolioEntries(data: DeliveryPortfolioResponse | undefined): PortfolioEntry[] {
  if (!data) return [];
  const entries: PortfolioEntry[] = [];
  for (const entry of data.projects) {
    const project = projectFromDashboard(entry.project_id, entry.dashboard);
    if (project) entries.push({ project, dashboard: entry.dashboard });
  }
  return entries;
}

/**
 * Attention ranking, worst first.
 *
 * Deliberately NOT business impact: the schema carries no contract value, headcount or
 * client tier, so a critical risk on a pilot still outranks a medium risk on the largest
 * account. `daily_target_units` is used only as a tie-break scale proxy. Ranking by real
 * business impact needs a new field and a product decision.
 */
const RISK_RANK: Record<string, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

function riskRank(dashboard: DeliveryDashboardResponse): number {
  // An unscored project is not implicitly safe, but it is not evidence of risk either;
  // it sorts below every scored tier so real signals stay at the top.
  if (!hasSufficientData(dashboard)) return 0;
  return RISK_RANK[riskTier(dashboard) ?? ""] ?? 0;
}

/**
 * Order by attention need, worst first. Every comparison ends in an id tie-break, so the
 * result is a total order: the same portfolio always yields the same sequence, and the
 * same head element, regardless of the payload's arrival order.
 */
export function sortByPriority(entries: PortfolioEntry[]): PortfolioEntry[] {
  return [...entries].sort((a, b) => {
    const rankDelta = riskRank(b.dashboard) - riskRank(a.dashboard);
    if (rankDelta !== 0) return rankDelta;

    // Lower confidence needs attention sooner.
    const confidenceDelta = a.dashboard.confidence - b.dashboard.confidence;
    if (confidenceDelta !== 0) return confidenceDelta;

    // Scale proxy: at equal risk and confidence, the larger commitment goes first.
    const scaleDelta = (b.project.daily_target_units ?? 0) - (a.project.daily_target_units ?? 0);
    if (scaleDelta !== 0) return scaleDelta;

    const nameDelta = a.project.name.localeCompare(b.project.name);
    if (nameDelta !== 0) return nameDelta;
    return a.project.id.localeCompare(b.project.id);
  });
}

/**
 * Pick the focused project: the URL wins when it names a project in the portfolio,
 * otherwise the highest-priority one. Never an arbitrary array head.
 */
export function resolveDefaultProjectId(
  rankedEntries: PortfolioEntry[],
  urlProjectId?: string,
): string | null {
  if (rankedEntries.length === 0) return null;
  if (urlProjectId && rankedEntries.some((entry) => entry.project.id === urlProjectId)) {
    return urlProjectId;
  }
  return rankedEntries[0]?.project.id ?? null;
}

export type PortfolioKpis = {
  totalThroughput: number;
  avgConfidence: number;
  atRiskProjects: number;
  milestoneHitRate: number | null;
};

export function computeMilestoneHitRate(milestones: Array<Record<string, unknown>>): number | null {
  const closed = milestones.filter(
    (milestone) => milestone.status === "completed" || milestone.status === "missed",
  );
  if (closed.length === 0) return null;
  const hit = closed.filter((milestone) => milestone.status === "completed").length;
  return Math.round((hit / closed.length) * 100);
}

/**
 * KPIs over the whole portfolio.
 *
 * Takes the full entry list, never a page slice: pagination is a view window over the
 * same universe, so paging must not move these numbers.
 */
export function computePortfolioKpis(
  entries: PortfolioEntry[],
  milestones: Array<Record<string, unknown>>,
): PortfolioKpis {
  const dashboards = entries.map((entry) => entry.dashboard);
  const scored = dashboards.filter((dashboard) => hasSufficientData(dashboard));

  const totalThroughput = dashboards.reduce(
    (sum, dashboard) => sum + avgDailyThroughputUnits(dashboard),
    0,
  );
  const avgConfidence =
    scored.length > 0
      ? scored.reduce((sum, dashboard) => sum + dashboard.confidence, 0) / scored.length
      : 0;
  const atRiskProjects = scored.filter((dashboard) => dashboard.traffic_light !== "green").length;

  return {
    totalThroughput,
    avgConfidence: Math.round(avgConfidence),
    atRiskProjects,
    milestoneHitRate: computeMilestoneHitRate(milestones),
  };
}
