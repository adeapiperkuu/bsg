import type { GovernanceKpis } from "@/types/governance";

export const GOVERNANCE_ANALYTICS_DEFER_MS = 200;
export const GOVERNANCE_ANALYTICS_DETAIL_IDLE_MS = 400;

const EMPTY_KPIS: GovernanceKpis = {
  open_actions: 0,
  overdue_actions: 0,
  open_escalations: 0,
  blocking_dependencies: 0,
  at_risk_items: 0,
  sla_adherence_pct: 100,
};

export function shouldEnableGovernanceAnalytics(
  showExecutiveAnalytics: boolean,
  analyticsDeferredReady: boolean,
): boolean {
  return showExecutiveAnalytics && analyticsDeferredReady;
}

export function shouldEnableGovernanceAnalyticsSummary(
  showExecutiveAnalytics: boolean,
  analyticsDeferredReady: boolean,
): boolean {
  return shouldEnableGovernanceAnalytics(showExecutiveAnalytics, analyticsDeferredReady);
}

export function shouldEnableGovernanceAnalyticsDetail(input: {
  showExecutiveAnalytics: boolean;
  analyticsDeferredReady: boolean;
  summaryReady: boolean;
  detailTriggerReady: boolean;
}): boolean {
  return (
    shouldEnableGovernanceAnalyticsSummary(
      input.showExecutiveAnalytics,
      input.analyticsDeferredReady,
    ) &&
    input.summaryReady &&
    input.detailTriggerReady
  );
}

export function shouldEnableGovernanceProjects(input: {
  filtersOpen: boolean;
  dialogOpen: boolean;
  agentNeedsProjects: boolean;
  chartersTabActive: boolean;
}): boolean {
  return (
    input.filtersOpen ||
    input.dialogOpen ||
    input.agentNeedsProjects ||
    input.chartersTabActive
  );
}

export function resolveGovernanceTabTotals(input: {
  bootstrapKpis?: GovernanceKpis | null;
  dependenciesTotal?: number;
  actionsTotal?: number;
  escalationsTotal?: number;
  registerTotal?: number;
}): {
  dependencies: number;
  actions: number;
  escalations: number;
  register: number;
} {
  const kpis = input.bootstrapKpis ?? EMPTY_KPIS;

  return {
    dependencies: input.dependenciesTotal ?? 0,
    actions: input.actionsTotal ?? kpis.open_actions,
    escalations: input.escalationsTotal ?? kpis.open_escalations,
    register: input.registerTotal ?? 0,
  };
}

export function collectProjectNamesFromGovernanceRows(
  rows: Array<{ project_id: string; project_name?: string | null }>,
): Map<string, string> {
  const names = new Map<string, string>();
  for (const row of rows) {
    if (row.project_name) {
      names.set(row.project_id, row.project_name);
    }
  }
  return names;
}
