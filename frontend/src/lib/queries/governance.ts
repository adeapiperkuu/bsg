import { queryOptions, useQuery } from "@tanstack/react-query";
import { apiFetch, apiFetchBlob } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type {
  GovernanceAction,
  GovernanceActionCreatePayload,
  GovernanceActionListItem,
  GovernanceActionUpdatePayload,
  GovernanceAnalytics,
  GovernanceBootstrap,
  GovernanceEscalation,
  GovernanceEscalationCreatePayload,
  GovernanceEscalationListItem,
  GovernanceEscalationUpdatePayload,
  GovernanceListParams,
  GovernanceListPagination,
  GovernanceRegisterRowApi,
  GovernanceWeeklySummary,
  GovernanceWeeklySummaryCreatePayload,
  PaginatedGovernanceList,
  ProjectCharter,
  ProjectCharterGeneratePayload,
  ProjectCharterUpdatePayload,
  ProjectDependency,
  ProjectDependencyCreatePayload,
  ProjectDependencyListItem,
  ProjectDependencyUpdatePayload,
  ProjectScopeState,
  ProjectScopeStateUpdatePayload,
} from "@/types/governance";

function governanceListQueryString(params?: GovernanceListParams): string {
  if (!params) return "";
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      qs.set(key, String(value));
    }
  });
  const text = qs.toString();
  return text ? `?${text}` : "";
}

function toPaginatedGovernanceList<T>(body: {
  data: T[];
  pagination?: Partial<GovernanceListPagination>;
}): PaginatedGovernanceList<T> {
  return {
    items: body.data,
    total: body.pagination?.total ?? body.data.length,
    limit: body.pagination?.limit ?? body.data.length,
    offset: body.pagination?.offset ?? 0,
    has_more: body.pagination?.has_more ?? false,
  };
}

export async function deleteDependency(dependencyId: string): Promise<void> {
  await apiFetch<void>(`/dependencies/${dependencyId}`, { method: "DELETE" });
}

export async function deleteGovernanceEscalation(escalationId: string): Promise<void> {
  await apiFetch<void>(`/governance/escalations/${escalationId}`, { method: "DELETE" });
}

export async function deleteGovernanceAction(actionId: string): Promise<void> {
  await apiFetch<void>(`/governance/actions/${actionId}`, { method: "DELETE" });
}

export async function promoteRiskAlertToEscalation(
  riskAlertId: string,
): Promise<GovernanceEscalation> {
  const body = await apiFetch<{ data: GovernanceEscalation }>(
    "/governance/escalations/promote-from-risk-alert",
    {
      method: "POST",
      body: JSON.stringify({ risk_alert_id: riskAlertId }),
    },
  );
  return body.data;
}

export type GovernanceWeeklySummaryUpdatePayload = {
  summary_text: string;
};

export async function listProjectCharters(projectId?: string): Promise<ProjectCharter[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const body = await apiFetch<{ data: ProjectCharter[] }>(`/governance/project-charters${qs}`);
  return body.data;
}

export async function generateProjectCharter(
  payload: ProjectCharterGeneratePayload,
): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>("/governance/project-charters/generate", {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateProjectCharter(
  charterId: string,
  payload: ProjectCharterUpdatePayload,
): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export async function approveProjectCharter(charterId: string): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}/approve`,
    { method: "POST" },
  );
  return body.data;
}

export async function archiveProjectCharter(charterId: string): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}/archive`,
    { method: "POST" },
  );
  return body.data;
}

export async function exportProjectCharter(
  charterId: string,
  format: "pdf" | "docx",
): Promise<Blob> {
  return apiFetchBlob(`/governance/project-charters/${charterId}/export.${format}`);
}

export async function listGovernanceWeeklySummaries(): Promise<GovernanceWeeklySummary[]> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary[] }>("/governance/weekly-summaries");
  return body.data;
}

export async function generateGovernanceWeeklySummary(
  summaryWeek?: string,
): Promise<GovernanceWeeklySummary> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary }>(
    "/governance/weekly-summary/generate",
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify(summaryWeek ? { summary_week: summaryWeek } : {}),
    },
  );
  return body.data;
}

export async function updateGovernanceWeeklySummary(
  summaryId: string,
  payload: GovernanceWeeklySummaryUpdatePayload,
): Promise<GovernanceWeeklySummary> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary }>(
    `/governance/weekly-summary/${summaryId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export async function approveGovernanceWeeklySummary(
  summaryId: string,
): Promise<GovernanceWeeklySummary> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary }>(
    `/governance/weekly-summary/${summaryId}/approve`,
    { method: "POST" },
  );
  return body.data;
}

export async function getGovernanceBootstrap(): Promise<GovernanceBootstrap> {
  const body = await apiFetch<{ data: GovernanceBootstrap }>("/governance/bootstrap");
  return body.data;
}

export async function getGovernanceAnalytics(days = 30): Promise<GovernanceAnalytics> {
  const body = await apiFetch<{ data: GovernanceAnalytics }>(
    `/governance/analytics?days=${encodeURIComponent(String(days))}`,
  );
  return body.data;
}

export async function exportGovernanceAnalytics(
  days: number,
  format: "csv" | "pdf",
): Promise<Blob> {
  return apiFetchBlob(
    `/governance/analytics/export.${format}?days=${encodeURIComponent(String(days))}`,
  );
}

export const governanceBootstrapQueryOptions = queryOptions({
  queryKey: queryKeys.governanceBootstrap,
  queryFn: getGovernanceBootstrap,
  staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  refetchOnMount: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
});

export function useGovernanceBootstrapQuery() {
  return useQuery(governanceBootstrapQueryOptions);
}

export function governanceAnalyticsQueryOptions(days: number) {
  return queryOptions({
    queryKey: queryKeys.governanceAnalytics(days),
    queryFn: () => getGovernanceAnalytics(days),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export async function getProjectDependencies(
  projectId: string,
): Promise<ProjectDependencyListItem[]> {
  const body = await apiFetch<{ data: ProjectDependencyListItem[] }>(
    `/projects/${projectId}/dependencies`,
  );
  return body.data;
}

export async function getGovernanceDependencies(
  params?: GovernanceListParams,
): Promise<PaginatedGovernanceList<ProjectDependencyListItem>> {
  const body = await apiFetch<{
    data: ProjectDependencyListItem[];
    pagination?: Partial<GovernanceListPagination>;
  }>(`/governance/dependencies${governanceListQueryString(params)}`);
  return toPaginatedGovernanceList(body);
}

export async function getDependency(dependencyId: string): Promise<ProjectDependency> {
  const body = await apiFetch<{ data: ProjectDependency }>(`/dependencies/${dependencyId}`);
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
  const body = await apiFetch<{ data: ProjectDependency }>(
    `/dependencies/${dependencyId}/resolve`,
    {
      method: "POST",
    },
  );
  return body.data;
}

export async function getGovernanceEscalations(
  params?: GovernanceListParams,
): Promise<PaginatedGovernanceList<GovernanceEscalationListItem>> {
  const body = await apiFetch<{
    data: GovernanceEscalationListItem[];
    pagination?: Partial<GovernanceListPagination>;
  }>(`/governance/escalations${governanceListQueryString(params)}`);
  return toPaginatedGovernanceList(body);
}

export async function getEscalation(escalationId: string): Promise<GovernanceEscalation> {
  const body = await apiFetch<{ data: GovernanceEscalation }>(
    `/governance/escalations/${escalationId}`,
  );
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

export async function getGovernanceActions(
  params?: GovernanceListParams,
): Promise<PaginatedGovernanceList<GovernanceActionListItem>> {
  const body = await apiFetch<{
    data: GovernanceActionListItem[];
    pagination?: Partial<GovernanceListPagination>;
  }>(`/governance/actions${governanceListQueryString(params)}`);
  return toPaginatedGovernanceList(body);
}

export async function getAction(actionId: string): Promise<GovernanceAction> {
  const body = await apiFetch<{ data: GovernanceAction }>(`/governance/actions/${actionId}`);
  return body.data;
}

export async function getGovernanceScopeStates(
  params?: GovernanceListParams,
): Promise<PaginatedGovernanceList<ProjectScopeState>> {
  const body = await apiFetch<{
    data: ProjectScopeState[];
    pagination?: Partial<GovernanceListPagination>;
  }>(`/governance/scope-states${governanceListQueryString(params)}`);
  return toPaginatedGovernanceList(body);
}

export async function getGovernanceRegister(
  params?: GovernanceListParams,
): Promise<PaginatedGovernanceList<GovernanceRegisterRowApi>> {
  const body = await apiFetch<{
    data: GovernanceRegisterRowApi[];
    pagination?: Partial<GovernanceListPagination>;
  }>(`/governance/register${governanceListQueryString(params)}`);
  return toPaginatedGovernanceList(body);
}

const governanceLazyQueryDefaults = {
  staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  refetchOnMount: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
};

export function governanceDependenciesQueryOptions(params?: GovernanceListParams) {
  return queryOptions({
    queryKey: queryKeys.governanceDependencies(params),
    queryFn: () => getGovernanceDependencies(params),
    ...governanceLazyQueryDefaults,
  });
}

export function governanceActionsQueryOptions(params?: GovernanceListParams) {
  return queryOptions({
    queryKey: queryKeys.governanceActions(params),
    queryFn: () => getGovernanceActions(params),
    ...governanceLazyQueryDefaults,
  });
}

export function governanceEscalationsQueryOptions(params?: GovernanceListParams) {
  return queryOptions({
    queryKey: queryKeys.governanceEscalations(params),
    queryFn: () => getGovernanceEscalations(params),
    ...governanceLazyQueryDefaults,
  });
}

export function governanceScopeStatesQueryOptions(params?: GovernanceListParams) {
  return queryOptions({
    queryKey: queryKeys.governanceScopeStates(params),
    queryFn: () => getGovernanceScopeStates(params),
    ...governanceLazyQueryDefaults,
  });
}

export function governanceRegisterQueryOptions(params?: GovernanceListParams) {
  return queryOptions({
    queryKey: queryKeys.governanceRegister(params),
    queryFn: () => getGovernanceRegister(params),
    ...governanceLazyQueryDefaults,
  });
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
  const body = await apiFetch<{ data: GovernanceWeeklySummary | null }>(
    "/governance/weekly-summary",
  );
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
