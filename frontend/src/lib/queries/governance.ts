import { queryOptions, type QueryClient } from "@tanstack/react-query";
import { apiFetch, apiFetchBlob } from "@/lib/api";
import { queryKeys, STALE_TIME_MS } from "@/lib/queries/keys";
import type {
  GovernanceAction,
  GovernanceActionCreatePayload,
  GovernanceActionListItem,
  GovernanceActionUpdatePayload,
  GovernanceAIRecommendation,
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
  GovernanceProjectSheet,
  GovernanceJob,
  GovernanceJobStart,
  GovernanceRegisterRowApi,
  GovernanceRecordEvidenceLink,
  GovernanceSourceRecommendation,
  GovernanceWeeklySummaryListItem,
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
} from "@/types/governance";

export type GovernanceJobListParams = {
  job_type?: string;
  project_id?: string;
  active_only?: boolean;
  limit?: number;
};

export async function getGovernanceJob(jobId: string): Promise<GovernanceJob> {
  const body = await apiFetch<{ data: GovernanceJob }>(`/governance/jobs/${jobId}`);
  return body.data;
}

export async function listGovernanceJobs(
  params: GovernanceJobListParams = {},
): Promise<GovernanceJob[]> {
  const qs = new URLSearchParams();
  if (params.job_type) qs.set("job_type", params.job_type);
  if (params.project_id) qs.set("project_id", params.project_id);
  if (params.active_only != null) qs.set("active_only", String(params.active_only));
  if (params.limit != null) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const body = await apiFetch<{ data: GovernanceJob[] }>(`/governance/jobs${suffix}`);
  return body.data;
}

export function governanceJobQueryOptions(jobId: string) {
  return queryOptions({
    queryKey: queryKeys.governanceJob(jobId),
    queryFn: () => getGovernanceJob(jobId),
    staleTime: 0,
  });
}

export function governanceJobsQueryOptions(params: GovernanceJobListParams = {}) {
  return queryOptions({
    queryKey: queryKeys.governanceJobs(params),
    queryFn: () => listGovernanceJobs(params),
    staleTime: 0,
  });
}

export async function cancelGovernanceJob(jobId: string): Promise<GovernanceJob> {
  const body = await apiFetch<{ data: GovernanceJob }>(`/governance/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
  });
  return body.data;
}

export async function retryGovernanceJob(jobId: string): Promise<GovernanceJob> {
  const body = await apiFetch<{ data: GovernanceJob }>(`/governance/jobs/${jobId}/retry`, {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
  });
  return body.data;
}

export async function downloadGovernanceJob(jobId: string): Promise<Blob> {
  return apiFetchBlob(`/governance/jobs/${jobId}/download`);
}

export async function getGovernanceWeeklySummary(): Promise<GovernanceWeeklySummary | null> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary | null }>(
    "/governance/weekly-summary",
  );
  return body.data;
}

export async function getGovernanceWeeklySummaryById(
  summaryId: string,
): Promise<GovernanceWeeklySummary> {
  const body = await apiFetch<{ data: GovernanceWeeklySummary }>(
    `/governance/weekly-summary/${summaryId}`,
  );
  return body.data;
}

export async function listGovernanceWeeklySummaries(
  limit = 12,
): Promise<GovernanceWeeklySummaryListItem[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    include_detail: "false",
  });
  const body = await apiFetch<{ data: GovernanceWeeklySummaryListItem[] }>(
    `/governance/weekly-summaries?${params.toString()}`,
  );
  return body.data;
}

export async function generateGovernanceWeeklySummary(): Promise<GovernanceJobStart> {
  const body = await apiFetch<{ data: GovernanceJobStart }>("/governance/weekly-summary/generate", {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
    body: JSON.stringify({}),
  });
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
  staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  refetchOnMount: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
});

export const governanceWeeklySummariesQueryOptions = queryOptions({
  queryKey: queryKeys.governanceWeeklySummaries,
  queryFn: () => listGovernanceWeeklySummaries(),
  staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
  refetchOnMount: false,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
});

export function governanceWeeklySummaryDetailQueryOptions(summaryId: string) {
  return queryOptions({
    queryKey: queryKeys.governanceWeeklySummaryDetail(summaryId),
    queryFn: () => getGovernanceWeeklySummaryById(summaryId),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

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

export type ProjectCharterListParams = {
  projectId?: string;
  selectedCharterId?: string | null;
  limit?: number;
  offset?: number;
  includeDetail?: boolean;
};

export async function listProjectCharters(
  projectIdOrParams?: string | ProjectCharterListParams,
): Promise<ProjectCharter[]> {
  const params =
    typeof projectIdOrParams === "string" ? { projectId: projectIdOrParams } : projectIdOrParams;
  const qs = new URLSearchParams();
  if (params?.projectId) qs.set("project_id", params.projectId);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  if (params?.includeDetail != null) qs.set("include_detail", String(params.includeDetail));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const body = await apiFetch<{ data: ProjectCharter[] }>(`/governance/project-charters${suffix}`);
  return body.data;
}

export async function getProjectChartersPanel(
  params: ProjectCharterListParams,
): Promise<import("@/types/governance").ProjectChartersPanelData> {
  const qs = new URLSearchParams();
  if (params.projectId) qs.set("project_id", params.projectId);
  if (params.selectedCharterId) qs.set("selected_charter_id", params.selectedCharterId);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const body = await apiFetch<{ data: import("@/types/governance").ProjectChartersPanelData }>(
    `/governance/project-charters/panel${suffix}`,
  );
  return body.data;
}

export function governanceProjectChartersPanelQueryOptions(params: ProjectCharterListParams) {
  return queryOptions({
    queryKey: queryKeys.governanceProjectChartersPanel(params),
    queryFn: () => getProjectChartersPanel(params),
    staleTime: Math.max(STALE_TIME_MS, 10 * 60 * 1000),
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export async function getProjectCharter(charterId: string): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}`,
  );
  return body.data;
}

export async function generateProjectCharter(
  payload: ProjectCharterGeneratePayload,
): Promise<GovernanceJobStart> {
  const body = await apiFetch<{ data: GovernanceJobStart }>(
    "/governance/project-charters/generate",
    {
      method: "POST",
      headers: { "X-BSG-User-Action": "true" },
      body: JSON.stringify(payload),
    },
  );
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

export async function unpublishProjectCharter(
  charterId: string,
  reason?: string,
): Promise<ProjectCharter> {
  const body = await apiFetch<{ data: ProjectCharter }>(
    `/governance/project-charters/${charterId}/unpublish`,
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
  format: "csv",
): Promise<GovernanceJobStart> {
  const normalized: GovernanceAnalyticsFilters =
    typeof filters === "number" ? { days: filters } : filters;
  const body = await apiFetch<{ data: GovernanceJobStart }>("/governance/analytics/exports", {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
    body: JSON.stringify({
      days: normalized.days,
      project_id: normalized.projectId ?? null,
      vertical: normalized.vertical ?? null,
      format,
    }),
  });
  return body.data;
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

export async function getGovernanceProjectSheet(
  projectId: string,
): Promise<GovernanceProjectSheet> {
  const body = await apiFetch<{ data: GovernanceProjectSheet }>(
    `/governance/project-sheet/${projectId}`,
  );
  return body.data;
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

export function governanceProjectSheetQueryOptions(projectId: string) {
  return queryOptions({
    queryKey: queryKeys.governanceProjectSheet(projectId),
    queryFn: () => getGovernanceProjectSheet(projectId),
    ...governanceLazyQueryDefaults,
  });
}

export function invalidateGovernanceProjectSheet(
  queryClient: QueryClient,
  projectId: string,
): Promise<void> {
  return queryClient.invalidateQueries({
    queryKey: queryKeys.governanceProjectSheet(projectId),
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
}): Promise<GovernanceJobStart> {
  const body = await apiFetch<{ data: GovernanceJobStart }>(
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
): Promise<GovernanceJobStart> {
  const body = await apiFetch<{ data: GovernanceJobStart }>(
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
