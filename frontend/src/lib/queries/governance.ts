import { apiFetch } from "@/lib/api";
import type {
  GovernanceAction,
  GovernanceActionCreatePayload,
  GovernanceBootstrap,
  GovernanceEscalation,
  GovernanceEscalationCreatePayload,
  GovernanceWeeklySummary,
  GovernanceWeeklySummaryCreatePayload,
  ProjectDependency,
  ProjectDependencyCreatePayload,
  ProjectScopeState,
  ProjectScopeStateUpdatePayload,
} from "@/types/governance";

export async function getGovernanceBootstrap(): Promise<GovernanceBootstrap> {
  const body = await apiFetch<{ data: GovernanceBootstrap }>("/governance/bootstrap");
  return body.data;
}

export async function listProjectDependencies(projectId: string): Promise<ProjectDependency[]> {
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

export async function resolveDependency(dependencyId: string): Promise<ProjectDependency> {
  const body = await apiFetch<{ data: ProjectDependency }>(`/dependencies/${dependencyId}/resolve`, {
    method: "POST",
  });
  return body.data;
}

export async function listGovernanceEscalations(): Promise<GovernanceEscalation[]> {
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

export async function listGovernanceActions(): Promise<GovernanceAction[]> {
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

export async function getGovernanceWeeklySummary(): Promise<GovernanceWeeklySummary | null> {
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
