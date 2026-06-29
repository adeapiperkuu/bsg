import { queryOptions, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type {
  GovernanceAction,
  GovernanceActionCreatePayload,
  GovernanceActionUpdatePayload,
  GovernanceBootstrap,
  GovernanceEscalation,
  GovernanceEscalationCreatePayload,
  GovernanceEscalationUpdatePayload,
  GovernanceWeeklySummary,
  GovernanceWeeklySummaryCreatePayload,
  ProjectDependency,
  ProjectDependencyCreatePayload,
  ProjectDependencyUpdatePayload,
  ProjectScopeState,
  ProjectScopeStateUpdatePayload,
} from "@/types/governance";

export async function deleteDependency(dependencyId: string): Promise<void> {
  await apiFetch<void>(`/dependencies/${dependencyId}`, { method: "DELETE" });
}

export async function deleteGovernanceEscalation(escalationId: string): Promise<void> {
  await apiFetch<void>(`/governance/escalations/${escalationId}`, { method: "DELETE" });
}

export async function deleteGovernanceAction(actionId: string): Promise<void> {
  await apiFetch<void>(`/governance/actions/${actionId}`, { method: "DELETE" });
}

export async function promoteRiskAlertToEscalation(riskAlertId: string): Promise<GovernanceEscalation> {
  const body = await apiFetch<{ data: GovernanceEscalation }>(
    "/governance/escalations/promote-from-risk-alert",
    {
      method: "POST",
      body: JSON.stringify({ risk_alert_id: riskAlertId }),
    },
  );
  return body.data;
}

export async function getGovernanceBootstrap(): Promise<GovernanceBootstrap> {
  const body = await apiFetch<{ data: GovernanceBootstrap }>("/governance/bootstrap");
  return body.data;
}

export const governanceBootstrapQueryOptions = queryOptions({
  queryKey: queryKeys.governanceBootstrap,
  queryFn: getGovernanceBootstrap,
  staleTime: STALE_TIME_MS,
});

export function useGovernanceBootstrapQuery() {
  return useQuery(governanceBootstrapQueryOptions);
}

export async function getProjectDependencies(projectId: string): Promise<ProjectDependency[]> {
  const body = await apiFetch<{ data: ProjectDependency[] }>(`/projects/${projectId}/dependencies`);
  return body.data;
}

export async function createProjectDependency(
  projectId: string,
  payload: ProjectDependencyCreatePayload,
): Promise<ProjectDependency> {
  const body = await apiFetch<{ data: ProjectDependency }>(`/projects/${projectId}/dependencies`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateDependency(
  dependencyId: string,
  payload: ProjectDependencyUpdatePayload,
): Promise<ProjectDependency> {
  const body = await apiFetch<{ data: ProjectDependency }>(`/dependencies/${dependencyId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function resolveDependency(dependencyId: string): Promise<ProjectDependency> {
  const body = await apiFetch<{ data: ProjectDependency }>(`/dependencies/${dependencyId}/resolve`, {
    method: "POST",
  });
  return body.data;
}

export async function getGovernanceEscalations(): Promise<GovernanceEscalation[]> {
  const body = await apiFetch<{ data: GovernanceEscalation[] }>("/governance/escalations");
  return body.data;
}

export async function createGovernanceEscalation(
  payload: GovernanceEscalationCreatePayload,
): Promise<GovernanceEscalation> {
  const body = await apiFetch<{ data: GovernanceEscalation }>("/governance/escalations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateGovernanceEscalation(
  escalationId: string,
  payload: GovernanceEscalationUpdatePayload,
): Promise<GovernanceEscalation> {
  const body = await apiFetch<{ data: GovernanceEscalation }>(
    `/governance/escalations/${escalationId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export async function getGovernanceActions(): Promise<GovernanceAction[]> {
  const body = await apiFetch<{ data: GovernanceAction[] }>("/governance/actions");
  return body.data;
}

export async function createGovernanceAction(
  payload: GovernanceActionCreatePayload,
): Promise<GovernanceAction> {
  const body = await apiFetch<{ data: GovernanceAction }>("/governance/actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateGovernanceAction(
  actionId: string,
  payload: GovernanceActionUpdatePayload,
): Promise<GovernanceAction> {
  const body = await apiFetch<{ data: GovernanceAction }>(`/governance/actions/${actionId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function getProjectScope(projectId: string): Promise<ProjectScopeState> {
  const body = await apiFetch<{ data: ProjectScopeState }>(`/projects/${projectId}/scope`);
  return body.data;
}

export async function updateProjectScope(
  projectId: string,
  payload: ProjectScopeStateUpdatePayload,
): Promise<ProjectScopeState> {
  const body = await apiFetch<{ data: ProjectScopeState }>(`/projects/${projectId}/scope`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function getWeeklySummary(): Promise<GovernanceWeeklySummary | null> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary | null }>("/governance/weekly-summary");
  return body.data;
}

export async function createGovernanceWeeklySummary(
  payload: GovernanceWeeklySummaryCreatePayload,
): Promise<GovernanceWeeklySummary> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary }>("/governance/weekly-summary", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

/** @deprecated Use getProjectDependencies */
export const listProjectDependencies = getProjectDependencies;
/** @deprecated Use getGovernanceEscalations */
export const listGovernanceEscalations = getGovernanceEscalations;
/** @deprecated Use getGovernanceActions */
export const listGovernanceActions = getGovernanceActions;
/** @deprecated Use getWeeklySummary */
export const getGovernanceWeeklySummary = getWeeklySummary;
