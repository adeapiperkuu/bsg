import { queryOptions } from "@tanstack/react-query";
import { apiFetch, apiFetchBlob } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type {
  GovernanceAction,
  GovernanceActionCreatePayload,
  GovernanceActionListItem,
  GovernanceActionUpdatePayload,
  GovernanceAIRecommendation,
  GovernanceAIRecommendationGenerationResult,
  GovernanceAIRecommendationList,
  GovernanceRecommendationConversion,
  GovernanceAnalytics,
  GovernanceAnalyticsDetail,
  GovernanceAnalyticsSummary,
  GovernanceBootstrap,
  GovernanceEffectivenessCategoryStat,
  GovernanceEffectivenessFilters,
  GovernanceEffectivenessFunnel,
  GovernanceEffectivenessSummary,
  GovernanceEffectivenessTrendPoint,
  GovernanceEscalation,
  GovernanceEscalationCreatePayload,
  GovernanceEscalationListItem,
  GovernanceEscalationUpdatePayload,
  GovernanceListParams,
  GovernanceListPagination,
  GovernanceWeeklySummary,
  GovernanceOptimizationCompare,
  GovernanceOptimizationSummary,
  GovernanceRegisterRowApi,
  GovernanceRecordEvidenceLink,
  GovernanceSourceRecommendation,
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
  ConvertRecommendationToActionPayload,
  ConvertRecommendationToEscalationPayload,
  EscalationSuggestionScanResult,
  EscalationSuggestionScanHistory,
} from "@/types/governance";

export async function getGovernanceWeeklySummary(): Promise<GovernanceWeeklySummary | null> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary | null }>(
    "/governance/weekly-summary",
  );
  return body.data;
}

export async function listGovernanceWeeklySummaries(
  limit = 12,
): Promise<GovernanceWeeklySummary[]> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary[] }>(
    `/governance/weekly-summaries?limit=${limit}`,
  );
  return body.data;
}

export async function generateGovernanceWeeklySummary(): Promise<GovernanceWeeklySummary> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary }>(
    "/governance/weekly-summary/generate",
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({}),
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

export async function exportGovernanceWeeklySummary(
  summaryId: string,
  format: "pdf" | "docx",
): Promise<Blob> {
  return apiFetchBlob(`/governance/weekly-summary/${summaryId}/export.${format}`);
}

export const governanceWeeklySummaryQueryOptions = queryOptions({
  queryKey: queryKeys.governanceWeeklySummary,
  queryFn: getGovernanceWeeklySummary,
  staleTime: STALE_TIME_MS,
});

export const governanceWeeklySummariesQueryOptions = queryOptions({
  queryKey: queryKeys.governanceWeeklySummaries,
  queryFn: () => listGovernanceWeeklySummaries(),
  staleTime: STALE_TIME_MS,
});

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

export async function publishClientEscalationSummary(
  escalationId: string,
  payload: { client_summary: string; client_visible?: boolean },
): Promise<GovernanceEscalation> {
  const body = await apiFetch<{ data: GovernanceEscalation }>(
    `/governance/escalations/${escalationId}/publish-client-summary`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

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

export async function publishProjectCharter(
  charterId: string,
  reason?: string,
): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}/publish`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
  return body.data;
}

export async function republishProjectCharter(
  charterId: string,
  reason?: string,
): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}/republish`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
  return body.data;
}

export async function retryProjectCharterPublication(
  charterId: string,
  reason?: string,
): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}/retry-publication`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
  return body.data;
}

export async function getProjectCharterPublicationStatus(
  charterId: string,
): Promise<import("@/types/governance").CharterPublicationStatus> {
  const body = await apiFetch<{ data: import("@/types/governance").CharterPublicationStatus }>(
    `/governance/project-charters/${charterId}/publication-status`,
  );
  return body.data;
}

export async function getProjectCharterKnowledge(
  charterId: string,
): Promise<import("@/types/governance").CharterKnowledgeLink> {
  const body = await apiFetch<{ data: import("@/types/governance").CharterKnowledgeLink }>(
    `/governance/project-charters/${charterId}/knowledge`,
  );
  return body.data;
}

export async function listProjectCharterPublicationVersions(
  charterId: string,
): Promise<import("@/types/governance").CharterPublicationVersion[]> {
  const body = await apiFetch<{ data: import("@/types/governance").CharterPublicationVersion[] }>(
    `/governance/project-charters/${charterId}/versions`,
  );
  return body.data;
}

export async function getGovernanceBootstrap(): Promise<GovernanceBootstrap> {
  const body = await apiFetch<{ data: GovernanceBootstrap }>("/governance/bootstrap");
  return body.data;
}

export type GovernanceAnalyticsFilters = {
  days?: number;
  projectId?: string | null;
  vertical?: string | null;
};

function analyticsQueryString(filters: GovernanceAnalyticsFilters): string {
  const params = new URLSearchParams();
  params.set("days", String(filters.days ?? 30));
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.vertical) params.set("vertical", filters.vertical);
  return params.toString();
}

export async function getGovernanceAnalyticsSummary(
  filters: GovernanceAnalyticsFilters | number = 30,
): Promise<GovernanceAnalyticsSummary> {
  const normalized: GovernanceAnalyticsFilters =
    typeof filters === "number" ? { days: filters } : filters;
  const body = await apiFetch<{ data: GovernanceAnalyticsSummary }>(
    `/governance/analytics/summary?${analyticsQueryString(normalized)}`,
  );
  return body.data;
}

export async function getGovernanceAnalyticsDetail(
  filters: GovernanceAnalyticsFilters | number = 30,
): Promise<GovernanceAnalyticsDetail> {
  const normalized: GovernanceAnalyticsFilters =
    typeof filters === "number" ? { days: filters } : filters;
  const body = await apiFetch<{ data: GovernanceAnalyticsDetail }>(
    `/governance/analytics/detail?${analyticsQueryString(normalized)}`,
  );
  return body.data;
}

export function mergeGovernanceAnalytics(
  summary: GovernanceAnalyticsSummary,
  detail?: GovernanceAnalyticsDetail | null,
): GovernanceAnalytics {
  return {
    generated_at: detail?.generated_at ?? summary.generated_at,
    date_range_days: summary.date_range_days,
    project_health: summary.project_health,
    portfolio_risk_ranking: summary.portfolio_risk_ranking,
    insights: detail?.insights ?? [],
    recommendations: detail?.recommendations ?? [],
    charts: { ...summary.charts, ...(detail?.charts ?? {}) },
    recent_activity: detail?.recent_activity ?? [],
    export_sections: [...summary.export_sections, ...(detail?.export_sections ?? [])],
    portfolio_governance_score:
      summary.portfolio_governance_score ??
      detail?.insights_kpis?.portfolio_governance_score ??
      null,
    insights_kpis: detail?.insights_kpis ?? summary.insights_kpis ?? null,
    top_governance_risks: detail?.top_governance_risks ?? [],
    top_recurring_blockers: detail?.top_recurring_blockers ?? [],
    top_recurring_mitigation_failures: detail?.top_recurring_mitigation_failures ?? [],
    most_affected_projects: detail?.most_affected_projects ?? [],
    most_affected_departments: detail?.most_affected_departments ?? [],
    risk_heatmap: detail?.risk_heatmap ?? [],
  };
}

export async function exportGovernanceAnalytics(
  filters: GovernanceAnalyticsFilters | number,
  format: "csv" | "pdf",
): Promise<Blob> {
  const normalized: GovernanceAnalyticsFilters =
    typeof filters === "number" ? { days: filters } : filters;
  return apiFetchBlob(`/governance/analytics/export.${format}?${analyticsQueryString(normalized)}`);
}

export const governanceBootstrapQueryOptions = queryOptions({
  queryKey: queryKeys.governanceBootstrap,
  queryFn: getGovernanceBootstrap,
  staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  refetchOnMount: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
});

export function governanceAnalyticsSummaryQueryOptions(
  daysOrFilters: number | GovernanceAnalyticsFilters,
) {
  const filters: GovernanceAnalyticsFilters =
    typeof daysOrFilters === "number" ? { days: daysOrFilters } : daysOrFilters;
  const days = filters.days ?? 30;
  return queryOptions({
    queryKey: queryKeys.governanceAnalyticsSummary(days, {
      projectId: filters.projectId,
      vertical: filters.vertical,
    }),
    queryFn: () => getGovernanceAnalyticsSummary(filters),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function governanceAnalyticsDetailQueryOptions(
  daysOrFilters: number | GovernanceAnalyticsFilters,
) {
  const filters: GovernanceAnalyticsFilters =
    typeof daysOrFilters === "number" ? { days: daysOrFilters } : daysOrFilters;
  const days = filters.days ?? 30;
  return queryOptions({
    queryKey: queryKeys.governanceAnalyticsDetail(days, {
      projectId: filters.projectId,
      vertical: filters.vertical,
    }),
    queryFn: () => getGovernanceAnalyticsDetail(filters),
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

export async function getEscalationEvidence(
  escalationId: string,
): Promise<GovernanceRecordEvidenceLink[]> {
  const body = await apiFetch<{ data: GovernanceRecordEvidenceLink[] }>(
    `/governance/escalations/${escalationId}/evidence`,
  );
  return body.data;
}

export async function getEscalationSourceRecommendation(
  escalationId: string,
): Promise<GovernanceSourceRecommendation | null> {
  const body = await apiFetch<{ data: GovernanceSourceRecommendation | null }>(
    `/governance/escalations/${escalationId}/source-recommendation`,
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

export async function getActionEvidence(actionId: string): Promise<GovernanceRecordEvidenceLink[]> {
  const body = await apiFetch<{ data: GovernanceRecordEvidenceLink[] }>(
    `/governance/actions/${actionId}/evidence`,
  );
  return body.data;
}

export async function getActionSourceRecommendation(
  actionId: string,
): Promise<GovernanceSourceRecommendation | null> {
  const body = await apiFetch<{ data: GovernanceSourceRecommendation | null }>(
    `/governance/actions/${actionId}/source-recommendation`,
  );
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

export type GovernanceAIRecommendationListParams = {
  project_id?: string;
  scope?: "project" | "portfolio";
  status?: string;
  limit?: number;
  offset?: number;
};

export async function listGovernanceAIRecommendations(
  params: GovernanceAIRecommendationListParams = {},
): Promise<GovernanceAIRecommendationList> {
  const qs = new URLSearchParams();
  if (params.project_id) qs.set("project_id", params.project_id);
  if (params.scope) qs.set("scope", params.scope);
  if (params.status) qs.set("status", params.status);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const body = await apiFetch<{ data: GovernanceAIRecommendationList }>(
    `/governance/ai-recommendations${suffix}`,
  );
  return body.data;
}

export function governanceAIRecommendationsQueryOptions(
  params: GovernanceAIRecommendationListParams = {},
) {
  return queryOptions({
    queryKey: queryKeys.governanceAIRecommendations(params),
    queryFn: () => listGovernanceAIRecommendations(params),
    staleTime: STALE_TIME_MS,
  });
}

export async function generateGovernanceAIRecommendations(payload: {
  project_id?: string;
  scope?: "project" | "portfolio";
  force?: boolean;
}): Promise<GovernanceAIRecommendationGenerationResult> {
  const body = await apiFetch<{ data: GovernanceAIRecommendationGenerationResult }>(
    "/governance/ai-recommendations/generate",
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({
        project_id: payload.project_id ?? null,
        scope: payload.scope ?? "project",
        force: payload.force ?? false,
      }),
    },
  );
  return body.data;
}

export async function regenerateGovernanceAIRecommendation(
  recommendationId: string,
): Promise<GovernanceAIRecommendationGenerationResult> {
  const body = await apiFetch<{ data: GovernanceAIRecommendationGenerationResult }>(
    `/governance/ai-recommendations/${recommendationId}/regenerate`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({}),
    },
  );
  return body.data;
}

export async function dismissGovernanceAIRecommendation(
  recommendationId: string,
  reason?: string,
): Promise<GovernanceAIRecommendation> {
  const body = await apiFetch<{ data: GovernanceAIRecommendation }>(
    `/governance/ai-recommendations/${recommendationId}/dismiss`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
  return body.data;
}

export async function submitGovernanceAIRecommendationFeedback(
  recommendationId: string,
  payload: { helpful: boolean; reason?: string },
): Promise<{ id: string; recommendation_id: string; helpful: boolean; reason: string | null }> {
  const body = await apiFetch<{
    data: { id: string; recommendation_id: string; helpful: boolean; reason: string | null };
  }>(`/governance/ai-recommendations/${recommendationId}/feedback`, {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function convertGovernanceAIRecommendationToAction(
  recommendationId: string,
  payload: ConvertRecommendationToActionPayload,
): Promise<GovernanceRecommendationConversion> {
  const body = await apiFetch<{ data: GovernanceRecommendationConversion }>(
    `/governance/ai-recommendations/${recommendationId}/convert/action`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export async function convertGovernanceAIRecommendationToEscalation(
  recommendationId: string,
  payload: ConvertRecommendationToEscalationPayload,
): Promise<GovernanceRecommendationConversion> {
  const body = await apiFetch<{ data: GovernanceRecommendationConversion }>(
    `/governance/ai-recommendations/${recommendationId}/convert/escalation`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export async function listEscalationSuggestions(
  params: {
    project_id?: string;
    status?: string;
    trigger_type?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<GovernanceAIRecommendation[]> {
  const qs = new URLSearchParams();
  if (params.project_id) qs.set("project_id", params.project_id);
  if (params.status) qs.set("status", params.status);
  if (params.trigger_type) qs.set("trigger_type", params.trigger_type);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const body = await apiFetch<{ data: GovernanceAIRecommendation[] }>(
    `/governance/escalation-suggestions${suffix}`,
  );
  return body.data;
}

export function escalationSuggestionsQueryOptions(
  params: {
    project_id?: string;
    status?: string;
    limit?: number;
  } = {},
) {
  return queryOptions({
    queryKey: ["governance", "escalation-suggestions", params],
    queryFn: () => listEscalationSuggestions(params),
    staleTime: STALE_TIME_MS,
  });
}

export async function listEscalationSuggestionScans(
  params: {
    project_id?: string;
    limit?: number;
  } = {},
): Promise<EscalationSuggestionScanHistory[]> {
  const qs = new URLSearchParams();
  if (params.project_id) qs.set("project_id", params.project_id);
  if (params.limit != null) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const body = await apiFetch<{ data: EscalationSuggestionScanHistory[] }>(
    `/governance/escalation-suggestions/scans${suffix}`,
  );
  return body.data;
}

export function escalationSuggestionScansQueryOptions(
  params: {
    project_id?: string;
    limit?: number;
  } = {},
) {
  return queryOptions({
    queryKey: ["governance", "escalation-suggestion-scans", params],
    queryFn: () => listEscalationSuggestionScans(params),
    staleTime: STALE_TIME_MS,
  });
}

export async function scanEscalationSuggestions(payload: {
  project_id?: string;
  force?: boolean;
}): Promise<EscalationSuggestionScanResult> {
  const body = await apiFetch<{ data: EscalationSuggestionScanResult }>(
    "/governance/escalation-suggestions/scan",
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify({
        project_id: payload.project_id ?? null,
        force: payload.force ?? false,
      }),
    },
  );
  return body.data;
}

export async function snoozeEscalationSuggestion(
  suggestionId: string,
  payload: { days?: number; reason?: string } = {},
): Promise<GovernanceAIRecommendation> {
  const body = await apiFetch<{ data: GovernanceAIRecommendation }>(
    `/governance/escalation-suggestions/${suggestionId}/snooze`,
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

function effectivenessQueryString(filters: GovernanceEffectivenessFilters): string {
  const params = new URLSearchParams();
  params.set("days", String(filters.days ?? 30));
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.vertical) params.set("vertical", filters.vertical);
  if (filters.triggerType) params.set("trigger_type", filters.triggerType);
  if (filters.strategyVersion) params.set("strategy_version", filters.strategyVersion);
  if (filters.qualityBand) params.set("quality_band", filters.qualityBand);
  if (filters.confidenceBand) params.set("confidence_band", filters.confidenceBand);
  if (filters.status) params.set("status", filters.status);
  return params.toString();
}

function optimizationQueryString(filters: GovernanceEffectivenessFilters): string {
  return effectivenessQueryString(filters);
}

export async function getRecommendationEffectivenessSummary(
  filters: GovernanceEffectivenessFilters = {},
): Promise<GovernanceEffectivenessSummary> {
  const body = await apiFetch<{ data: GovernanceEffectivenessSummary }>(
    `/governance/insights/recommendations/effectiveness/summary?${effectivenessQueryString(filters)}`,
  );
  return body.data;
}

export async function getRecommendationOptimizationSummary(
  filters: GovernanceEffectivenessFilters = {},
): Promise<GovernanceOptimizationSummary> {
  const body = await apiFetch<{ data: GovernanceOptimizationSummary }>(
    `/governance/recommendations/optimization/summary?${optimizationQueryString(filters)}`,
  );
  return body.data;
}

export async function getRecommendationOptimizationCompare(
  strategyA: string,
  strategyB: string,
  days = 30,
): Promise<GovernanceOptimizationCompare> {
  const params = new URLSearchParams({
    strategy_a: strategyA,
    strategy_b: strategyB,
    days: String(days),
  });
  const body = await apiFetch<{ data: GovernanceOptimizationCompare }>(
    `/governance/recommendations/optimization/compare?${params.toString()}`,
  );
  return body.data;
}

export async function generateRecommendationOptimizationReport(
  period: "weekly" | "monthly" | "quarterly" = "weekly",
): Promise<unknown> {
  const body = await apiFetch<{ data: unknown }>(
    `/governance/recommendations/optimization/reports?period=${period}`,
    { method: "POST" },
  );
  return body.data;
}

export async function getRecommendationEffectivenessFunnel(
  filters: GovernanceEffectivenessFilters = {},
): Promise<GovernanceEffectivenessFunnel> {
  const body = await apiFetch<{ data: GovernanceEffectivenessFunnel }>(
    `/governance/insights/recommendations/effectiveness/funnel?${effectivenessQueryString(filters)}`,
  );
  return body.data;
}

export async function getRecommendationEffectivenessTrends(
  filters: GovernanceEffectivenessFilters = {},
): Promise<{ points: GovernanceEffectivenessTrendPoint[] }> {
  const body = await apiFetch<{ data: { points: GovernanceEffectivenessTrendPoint[] } }>(
    `/governance/insights/recommendations/effectiveness/trends?${effectivenessQueryString(filters)}`,
  );
  return body.data;
}

export async function getFrequentlyDismissedCategories(
  filters: GovernanceEffectivenessFilters = {},
): Promise<GovernanceEffectivenessCategoryStat[]> {
  const body = await apiFetch<{ data: GovernanceEffectivenessCategoryStat[] }>(
    `/governance/insights/recommendations/effectiveness/frequently-dismissed?${effectivenessQueryString(filters)}`,
  );
  return body.data;
}

export async function getFrequentlyAcceptedCategories(
  filters: GovernanceEffectivenessFilters = {},
): Promise<GovernanceEffectivenessCategoryStat[]> {
  const body = await apiFetch<{ data: GovernanceEffectivenessCategoryStat[] }>(
    `/governance/insights/recommendations/effectiveness/frequently-accepted?${effectivenessQueryString(filters)}`,
  );
  return body.data;
}

export function recommendationEffectivenessSummaryQueryOptions(
  filters: GovernanceEffectivenessFilters,
) {
  return queryOptions({
    queryKey: queryKeys.governanceRecommendationEffectivenessSummary({
      days: filters.days ?? 30,
      projectId: filters.projectId ?? null,
      vertical: filters.vertical ?? null,
      triggerType: filters.triggerType ?? null,
    }),
    queryFn: () => getRecommendationEffectivenessSummary(filters),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  });
}

export function recommendationEffectivenessFunnelQueryOptions(
  filters: GovernanceEffectivenessFilters,
) {
  return queryOptions({
    queryKey: queryKeys.governanceRecommendationEffectivenessFunnel({
      days: filters.days ?? 30,
      projectId: filters.projectId ?? null,
      vertical: filters.vertical ?? null,
    }),
    queryFn: () => getRecommendationEffectivenessFunnel(filters),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  });
}

export function recommendationEffectivenessTrendsQueryOptions(
  filters: GovernanceEffectivenessFilters,
) {
  return queryOptions({
    queryKey: queryKeys.governanceRecommendationEffectivenessTrends({
      days: filters.days ?? 30,
      projectId: filters.projectId ?? null,
      vertical: filters.vertical ?? null,
    }),
    queryFn: () => getRecommendationEffectivenessTrends(filters),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  });
}

export function frequentlyDismissedCategoriesQueryOptions(filters: GovernanceEffectivenessFilters) {
  return queryOptions({
    queryKey: queryKeys.governanceRecommendationEffectivenessCategories("dismissed", {
      days: filters.days ?? 30,
      projectId: filters.projectId ?? null,
      vertical: filters.vertical ?? null,
    }),
    queryFn: () => getFrequentlyDismissedCategories(filters),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  });
}

export function frequentlyAcceptedCategoriesQueryOptions(filters: GovernanceEffectivenessFilters) {
  return queryOptions({
    queryKey: queryKeys.governanceRecommendationEffectivenessCategories("accepted", {
      days: filters.days ?? 30,
      projectId: filters.projectId ?? null,
      vertical: filters.vertical ?? null,
    }),
    queryFn: () => getFrequentlyAcceptedCategories(filters),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  });
}

export function recommendationOptimizationSummaryQueryOptions(
  filters: GovernanceEffectivenessFilters,
) {
  return queryOptions({
    queryKey: queryKeys.governanceRecommendationOptimizationSummary({
      days: filters.days ?? 30,
      projectId: filters.projectId ?? null,
      vertical: filters.vertical ?? null,
      strategyVersion: filters.strategyVersion ?? null,
    }),
    queryFn: () => getRecommendationOptimizationSummary(filters),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  });
}

export function recommendationOptimizationCompareQueryOptions(
  strategyA: string,
  strategyB: string,
  days = 30,
) {
  return queryOptions({
    queryKey: queryKeys.governanceRecommendationOptimizationCompare(strategyA, strategyB, days),
    queryFn: () => getRecommendationOptimizationCompare(strategyA, strategyB, days),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
    enabled: Boolean(strategyA && strategyB && strategyA !== strategyB),
  });
}
