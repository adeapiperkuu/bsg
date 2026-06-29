import type {
  GovernanceAction,
  GovernanceBootstrap,
  GovernanceEscalation,
  GovernanceEscalationSeverity,
  GovernanceScopeStatus,
  ProjectDependency,
} from "@/types/governance";
import type { DeliveryPortfolioResponse } from "@/lib/api";

export type GovernanceHealth = "Green" | "Amber" | "Red";

export type GovernanceRegisterRow = {
  projectId: string;
  projectName: string;
  scopeStatus: GovernanceScopeStatus | null;
  scopeVersion: string | null;
  openDependencies: number;
  blockingDependencies: number;
  openActions: number;
  openEscalations: number;
  health: GovernanceHealth;
  deliveryTrafficLight: "green" | "yellow" | "red" | null;
  deliveryConfidence: number | null;
  atRiskMilestones: number;
};

const OPEN_ACTION_STATUSES = new Set(["open", "in_progress", "overdue"]);
const OPEN_ESCALATION_STATUSES = new Set(["open", "in_progress"]);
const OPEN_DEPENDENCY_STATUSES = new Set(["open", "blocking"]);

export function formatScopeStatus(status: GovernanceScopeStatus | null): string {
  if (!status) return "—";
  if (status === "approved") return "Approved";
  if (status === "pending_revision") return "Pending Revision";
  return "Locked";
}

export function formatDependencyType(type: string): string {
  return type
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatDependencyStatus(status: string): string {
  if (status === "blocking") return "Blocking";
  if (status === "resolved") return "Resolved";
  return "Open";
}

export function formatEscalationSeverity(severity: GovernanceEscalationSeverity): string {
  return severity.charAt(0).toUpperCase() + severity.slice(1);
}

export function formatEscalationStatus(status: string): string {
  if (status === "in_progress") return "In Progress";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function formatActionStatus(status: string): string {
  if (status === "in_progress") return "In Progress";
  if (status === "overdue") return "Overdue";
  if (status === "completed") return "Completed";
  return "Open";
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function mondayOfWeek(ref: Date): Date {
  const date = new Date(ref);
  const day = date.getDay();
  const diff = date.getDate() - day + (day === 0 ? -6 : 1);
  date.setDate(diff);
  date.setHours(0, 0, 0, 0);
  return date;
}

function sundayOfWeek(ref: Date): Date {
  const monday = mondayOfWeek(ref);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  sunday.setHours(23, 59, 59, 999);
  return sunday;
}

export function isDueThisWeek(dueDate: string | null, ref = new Date()): boolean {
  if (!dueDate) return false;
  const due = new Date(`${dueDate}T12:00:00`);
  if (Number.isNaN(due.getTime())) return false;
  return due >= mondayOfWeek(ref) && due <= sundayOfWeek(ref);
}

export function isOverdueAction(action: GovernanceAction, ref = new Date()): boolean {
  if (action.status === "overdue") return true;
  if (action.status === "completed" || !action.due_date) return false;
  const due = new Date(`${action.due_date}T23:59:59`);
  return due < ref;
}

export function computeProjectHealth(
  projectId: string,
  data: Pick<GovernanceBootstrap, "dependencies" | "escalations" | "actions" | "scope_states">,
): GovernanceHealth {
  const scope = data.scope_states.find((row) => row.project_id === projectId);
  const deps = data.dependencies.filter((row) => row.project_id === projectId);
  const escs = data.escalations.filter((row) => row.project_id === projectId);
  const acts = data.actions.filter((row) => row.project_id === projectId);

  const hasCriticalEscalation = escs.some(
    (row) => OPEN_ESCALATION_STATUSES.has(row.status) && row.severity === "critical",
  );
  const hasBlockingOverdue = deps.some(
    (row) => row.status === "blocking" && row.overdue_days > 0,
  );
  if (hasCriticalEscalation || hasBlockingOverdue) return "Red";

  const hasOpenEscalation = escs.some((row) => OPEN_ESCALATION_STATUSES.has(row.status));
  const hasPendingScope = scope?.scope_status === "pending_revision";
  const hasOverdueAction = acts.some((row) => isOverdueAction(row));
  if (hasOpenEscalation || hasPendingScope || hasOverdueAction) return "Amber";

  return "Green";
}

function deliveryContextForProject(
  projectId: string,
  portfolio: DeliveryPortfolioResponse | undefined,
) {
  const entry = portfolio?.projects.find((row) => row.project_id === projectId);
  if (!entry) {
    return { trafficLight: null, confidence: null, atRiskMilestones: 0 };
  }
  const overview = entry.dashboard.overview as Record<string, unknown> | undefined;
  const confidence = overview?.confidence_score;
  const milestones = Array.isArray(entry.dashboard.milestones) ? entry.dashboard.milestones : [];
  const atRiskMilestones = milestones.filter((row) => {
    const record = row as Record<string, unknown>;
    return record.status === "at_risk";
  }).length;
  return {
    trafficLight: entry.dashboard.traffic_light ?? null,
    confidence: typeof confidence === "number" ? confidence : null,
    atRiskMilestones,
  };
}

export function buildGovernanceRegister(
  data: GovernanceBootstrap,
  portfolio?: DeliveryPortfolioResponse,
): GovernanceRegisterRow[] {
  const projectIds = new Set<string>();
  const projectNames = new Map<string, string>();

  for (const row of data.scope_states) {
    projectIds.add(row.project_id);
  }
  for (const row of data.dependencies) {
    projectIds.add(row.project_id);
    if (row.project_name) projectNames.set(row.project_id, row.project_name);
  }
  for (const row of data.actions) {
    projectIds.add(row.project_id);
    if (row.project_name) projectNames.set(row.project_id, row.project_name);
  }
  for (const row of data.escalations) {
    projectIds.add(row.project_id);
    if (row.project_name) projectNames.set(row.project_id, row.project_name);
  }
  for (const row of portfolio?.projects ?? []) {
    projectIds.add(row.project_id);
  }

  const scopeByProject = new Map(data.scope_states.map((row) => [row.project_id, row]));

  return Array.from(projectIds)
    .map((projectId) => {
      const scope = scopeByProject.get(projectId);
      const deps = data.dependencies.filter((row) => row.project_id === projectId);
      const acts = data.actions.filter(
        (row) => row.project_id === projectId && OPEN_ACTION_STATUSES.has(row.status),
      );
      const escs = data.escalations.filter(
        (row) => row.project_id === projectId && OPEN_ESCALATION_STATUSES.has(row.status),
      );
      const delivery = deliveryContextForProject(projectId, portfolio);

      return {
        projectId,
        projectName:
          projectNames.get(projectId) ??
          data.dependencies.find((row) => row.project_id === projectId)?.project_name ??
          data.actions.find((row) => row.project_id === projectId)?.project_name ??
          data.escalations.find((row) => row.project_id === projectId)?.project_name ??
          projectId.slice(0, 8),
        scopeStatus: scope?.scope_status ?? null,
        scopeVersion: scope?.version_label ?? null,
        openDependencies: deps.filter((row) => OPEN_DEPENDENCY_STATUSES.has(row.status)).length,
        blockingDependencies: deps.filter((row) => row.status === "blocking").length,
        openActions: acts.length,
        openEscalations: escs.length,
        health: computeProjectHealth(projectId, data),
        deliveryTrafficLight: delivery.trafficLight,
        deliveryConfidence: delivery.confidence,
        atRiskMilestones: delivery.atRiskMilestones,
      };
    })
    .sort((a, b) => a.projectName.localeCompare(b.projectName));
}

export function actionsDueThisWeek(actions: GovernanceAction[]): GovernanceAction[] {
  return actions.filter(
    (action) =>
      OPEN_ACTION_STATUSES.has(action.status) && isDueThisWeek(action.due_date),
  );
}

export function overdueActions(actions: GovernanceAction[]): GovernanceAction[] {
  return actions.filter((action) => isOverdueAction(action));
}

export function dependencyRowClass(dep: ProjectDependency): string {
  if (dep.status === "blocking" || dep.overdue_days > 0) {
    return "bg-[color:var(--danger)]/5";
  }
  if (dep.status === "resolved") return "opacity-70";
  return "";
}

export function escalationRowClass(esc: GovernanceEscalation): string {
  if (esc.severity === "critical" || esc.severity === "high") {
    return "bg-[color:var(--danger)]/5";
  }
  return "";
}
