/**
 * Phase 15.6 — deterministic derivations for the redesigned Delivery dashboard.
 *
 * Pure functions over payloads the page already loads (portfolio dashboards,
 * root-cause trends, PM action history). No new queries, no AI.
 */
import type {
  DeliveryDashboardResponse,
  PmDailyActionRead,
  RootCauseTrendsResponse,
} from "@/lib/api";
import type { PortfolioEntry } from "@/features/delivery/portfolio";
import { hasSufficientData, riskTier } from "@/features/delivery/portfolio";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function parseDate(value: unknown): Date | null {
  if (typeof value !== "string" || !value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

// ---------------------------------------------------------------------------
// Traffic-light distribution (Executive overview)
// ---------------------------------------------------------------------------

export type TrafficDistribution = {
  green: number;
  yellow: number;
  red: number;
  insufficient: number;
  total: number;
};

export function deriveTrafficDistribution(entries: PortfolioEntry[]): TrafficDistribution {
  const dist: TrafficDistribution = {
    green: 0,
    yellow: 0,
    red: 0,
    insufficient: 0,
    total: entries.length,
  };
  for (const { dashboard } of entries) {
    if (!hasSufficientData(dashboard)) {
      dist.insufficient += 1;
      continue;
    }
    if (dashboard.traffic_light === "green") dist.green += 1;
    else if (dashboard.traffic_light === "red") dist.red += 1;
    else dist.yellow += 1;
  }
  return dist;
}

// ---------------------------------------------------------------------------
// Team bottlenecks
// ---------------------------------------------------------------------------

export type BottleneckRow = {
  id: string;
  title: string;
  detail: string;
  status: string;
  severity: "low" | "medium" | "high" | "critical";
  teamKey: string;
  createdAt: string | null;
};

const SEVERITY_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };
const ACTIVE_BOTTLENECK_STATUSES = new Set(["open", "acknowledged"]);

export function deriveActiveBottlenecks(
  dashboard: DeliveryDashboardResponse | undefined,
): BottleneckRow[] {
  const rows: BottleneckRow[] = [];
  for (const raw of dashboard?.bottlenecks ?? []) {
    const item = asRecord(raw);
    if (!item) continue;
    const status = str(item.status).toLowerCase();
    if (!ACTIVE_BOTTLENECK_STATUSES.has(status)) continue;
    const severity = str(item.severity).toLowerCase();
    rows.push({
      id: str(item.id),
      title: str(item.title) || "Untitled bottleneck",
      detail: str(item.detail),
      status,
      severity: (SEVERITY_RANK[severity] ? severity : "medium") as BottleneckRow["severity"],
      teamKey: str(item.team_id) || "unassigned",
      createdAt: str(item.created_at) || null,
    });
  }
  return rows.sort(
    (a, b) =>
      (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0) ||
      a.title.localeCompare(b.title),
  );
}

// ---------------------------------------------------------------------------
// Operational timeline
// ---------------------------------------------------------------------------

export type TimelineEvent = {
  key: string;
  date: Date;
  kind: "risk" | "bottleneck" | "milestone" | "action";
  title: string;
  detail: string;
  tone: "danger" | "warning" | "info" | "success";
};

export function buildOperationalTimeline(
  dashboard: DeliveryDashboardResponse | undefined,
  actionHistory: PmDailyActionRead[] = [],
  limit = 20,
): TimelineEvent[] {
  const events: TimelineEvent[] = [];

  for (const raw of dashboard?.risks ?? []) {
    const risk = asRecord(raw);
    const created = parseDate(risk?.created_at);
    if (!risk || !created) continue;
    events.push({
      key: `risk-${str(risk.id)}`,
      date: created,
      kind: "risk",
      title: str(risk.title) || "Risk opened",
      detail: `Risk opened · ${str(risk.risk_tier) || "unknown"} tier`,
      tone: "danger",
    });
  }

  for (const raw of dashboard?.bottlenecks ?? []) {
    const bottleneck = asRecord(raw);
    const created = parseDate(bottleneck?.created_at);
    if (!bottleneck || !created) continue;
    const status = str(bottleneck.status).toLowerCase();
    events.push({
      key: `bottleneck-${str(bottleneck.id)}`,
      date: created,
      kind: "bottleneck",
      title: str(bottleneck.title) || "Bottleneck detected",
      detail: `Bottleneck ${status || "open"} · ${str(bottleneck.severity) || "medium"} severity`,
      tone: "warning",
    });
  }

  for (const raw of dashboard?.milestones ?? []) {
    const milestone = asRecord(raw);
    if (!milestone) continue;
    const status = str(milestone.status).toLowerCase();
    const name = str(milestone.name) || "Milestone";
    const actual = parseDate(milestone.actual_date);
    const planned = parseDate(milestone.planned_date);
    if (actual) {
      events.push({
        key: `milestone-${str(milestone.id)}-actual`,
        date: actual,
        kind: "milestone",
        title: name,
        detail: `Milestone ${status || "completed"}`,
        tone: status === "completed" ? "success" : "info",
      });
    } else if (planned && (status === "missed" || status === "at_risk")) {
      events.push({
        key: `milestone-${str(milestone.id)}-planned`,
        date: planned,
        kind: "milestone",
        title: name,
        detail: `Milestone ${status.replace("_", " ")} (planned)`,
        tone: "danger",
      });
    }
  }

  for (const action of actionHistory) {
    const completed = parseDate(action.completed_at);
    if (!completed) continue;
    events.push({
      key: `action-${action.id}`,
      date: completed,
      kind: "action",
      title: action.title,
      detail: `PM action ${action.status}`,
      tone: action.status === "done" ? "success" : "info",
    });
  }

  return events.sort((a, b) => b.date.getTime() - a.date.getTime()).slice(0, limit);
}

// ---------------------------------------------------------------------------
// Delivery insights
// ---------------------------------------------------------------------------

export type DeliveryInsight = {
  key: string;
  label: string;
  detail: string;
  tone: "danger" | "warning" | "info" | "success";
};

function countOpenItems(dashboard: DeliveryDashboardResponse): {
  risks: number;
  bottlenecks: number;
} {
  const overview = asRecord(dashboard.overview);
  return {
    risks: typeof overview?.open_risk_count === "number" ? overview.open_risk_count : 0,
    bottlenecks:
      typeof overview?.open_bottleneck_count === "number" ? overview.open_bottleneck_count : 0,
  };
}

export function deriveDeliveryInsights(
  entries: PortfolioEntry[],
  trends: RootCauseTrendsResponse | undefined,
): DeliveryInsight[] {
  const insights: DeliveryInsight[] = [];
  const dist = deriveTrafficDistribution(entries);

  if (dist.red > 0) {
    insights.push({
      key: "red-projects",
      label: `${dist.red} project${dist.red === 1 ? "" : "s"} at red status`,
      detail: "Prioritize root-cause review and today's PM actions for these projects.",
      tone: "danger",
    });
  }

  const scored = entries.filter((entry) => hasSufficientData(entry.dashboard));
  if (scored.length > 0) {
    const lowest = scored.reduce((min, entry) =>
      entry.dashboard.confidence < min.dashboard.confidence ? entry : min,
    );
    insights.push({
      key: "lowest-confidence",
      label: `Lowest confidence: ${lowest.project.name} (${Math.round(lowest.dashboard.confidence)}%)`,
      detail: `Risk tier ${riskTier(lowest.dashboard) ?? "unknown"} · check its briefing and focus list.`,
      tone: lowest.dashboard.confidence < 60 ? "danger" : "warning",
    });
  }

  const totals = entries.reduce(
    (acc, entry) => {
      const counts = countOpenItems(entry.dashboard);
      acc.risks += counts.risks;
      acc.bottlenecks += counts.bottlenecks;
      return acc;
    },
    { risks: 0, bottlenecks: 0 },
  );
  if (totals.risks + totals.bottlenecks > 0) {
    insights.push({
      key: "open-items",
      label: `${totals.risks} open risk${totals.risks === 1 ? "" : "s"} · ${totals.bottlenecks} active bottleneck${totals.bottlenecks === 1 ? "" : "s"}`,
      detail: "Across the visible portfolio.",
      tone: totals.risks + totals.bottlenecks > 5 ? "warning" : "info",
    });
  }

  const worsening = (trends?.factors ?? []).filter(
    (factor) => factor.trend_direction === "up" && factor.today !== null,
  );
  for (const factor of worsening.slice(0, 2)) {
    insights.push({
      key: `worsening-${factor.factor}`,
      label: `${factor.label} is worsening`,
      detail: `Impact today ${factor.today?.toFixed(1)}% vs last week ${
        factor.last_week === null ? "—" : `${factor.last_week.toFixed(1)}%`
      }.`,
      tone: "warning",
    });
  }

  const improving = (trends?.factors ?? []).filter(
    (factor) => factor.trend_direction === "down" && factor.today !== null,
  );
  if (improving.length > 0 && insights.length < 6) {
    const best = improving[0];
    insights.push({
      key: `improving-${best.factor}`,
      label: `${best.label} is improving`,
      detail: `Impact today ${best.today?.toFixed(1)}% — down from last week.`,
      tone: "success",
    });
  }

  if (dist.insufficient > 0) {
    insights.push({
      key: "insufficient-data",
      label: `${dist.insufficient} project${dist.insufficient === 1 ? "" : "s"} without throughput history`,
      detail: "Scores are not meaningful until throughput data is ingested.",
      tone: "info",
    });
  }

  if (insights.length === 0) {
    insights.push({
      key: "all-clear",
      label: "No portfolio-level alerts",
      detail: "All scored projects are green and no root-cause factor is worsening.",
      tone: "success",
    });
  }

  return insights.slice(0, 6);
}

// ---------------------------------------------------------------------------
// Drill-down helpers
// ---------------------------------------------------------------------------

export function trafficLightLabel(dashboard: DeliveryDashboardResponse | undefined): string {
  if (!dashboard || !hasSufficientData(dashboard)) return "Unknown";
  if (dashboard.traffic_light === "green") return "Green";
  if (dashboard.traffic_light === "red") return "Red";
  return "Amber";
}

export function milestoneHitRateFor(dashboard: DeliveryDashboardResponse | undefined): string {
  const milestones = dashboard?.milestones ?? [];
  const closed = milestones.filter((raw) => {
    const status = str(asRecord(raw)?.status);
    return status === "completed" || status === "missed";
  });
  if (closed.length === 0) return "—";
  const hit = closed.filter((raw) => str(asRecord(raw)?.status) === "completed").length;
  return `${Math.round((hit / closed.length) * 100)}%`;
}
