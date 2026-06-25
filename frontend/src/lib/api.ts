import type { AppRole, AuthSession, MeUser, OrganisationRead, UserRead } from "@/types/auth";
import type {
  AgentQueryCreate,
  AgentQueryRead,
  AnnotatorRead,
  CapabilityGapDetectionResponse,
  CapabilityGapRead,
  CapabilityGapUpdatePayload,
  ProjectUtilizationFilters,
  ProjectSkillRequirementRead,
  SkillMatrixRead,
  SkillRead,
  TeamRead,
  TrainingGapSummaryRead,
  UtilizationSnapshotRead,
  WorkforceRecommendationGenerateResponse,
} from "@/types/workforce";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ErrorBody = {
  error?: {
    code?: string;
    message?: string;
  };
};

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const err = body?.error;
    throw new ApiError(
      response.status,
      err?.code ?? "API_ERROR",
      err?.message ?? "Request failed.",
    );
  }
  return body as T;
}

async function parseApiError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => ({}))) as ErrorBody;
  const err = body?.error;
  return new ApiError(response.status, err?.code ?? "API_ERROR", err?.message ?? "Request failed.");
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  retried = false,
): Promise<T> {
  const headers = new Headers(init.headers);
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = (init.method ?? "GET").toUpperCase();
  if (["POST", "PATCH", "DELETE", "PUT"].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && !path.startsWith("/auth/") && !retried) {
    const error = await parseApiError(response);
    if (error.code === "AUTH_REQUIRED") throw error;
    const refreshed = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) {
      return apiFetch<T>(path, init, true);
    }
    throw error;
  }

  return parseResponse<T>(response);
}

export async function login(email: string, password: string): Promise<AuthSession> {
  const body = await apiFetch<{ data: AuthSession }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return body.data;
}

export async function logout(): Promise<void> {
  await apiFetch<void>("/auth/logout", { method: "POST" });
}

export async function fetchMe(): Promise<MeUser> {
  const body = await apiFetch<{ data: MeUser }>("/me");
  return body.data;
}

export async function listUsers(): Promise<UserRead[]> {
  const body = await apiFetch<{ data: UserRead[] }>("/users");
  return body.data;
}

export async function listOrganisations(): Promise<OrganisationRead[]> {
  const body = await apiFetch<{ data: OrganisationRead[] }>("/organisations");
  return body.data;
}

export type ProjectStatus = "active" | "ramping" | "paused" | "completed" | "cancelled";

export type ProjectRead = {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  vertical: string;
  status: ProjectStatus;
  start_date: string;
  target_end_date: string;
  actual_end_date: string | null;
  daily_target_units: number | null;
  created_at: string;
  updated_at: string;
};

export type ProjectCreatePayload = {
  name: string;
  description?: string | null;
  vertical: string;
  status?: ProjectStatus;
  start_date: string;
  target_end_date: string;
  daily_target_units?: number | null;
  org_id?: string | null;
};

export type ProjectUpdatePayload = {
  name?: string;
  description?: string | null;
  status?: ProjectStatus;
  target_end_date?: string;
  actual_end_date?: string | null;
  daily_target_units?: number | null;
};

export async function listProjects(): Promise<ProjectRead[]> {
  const body = await apiFetch<{ data: ProjectRead[] }>("/projects?limit=100");
  return body.data;
}

export async function getProject(projectId: string): Promise<ProjectRead> {
  const body = await apiFetch<{ data: ProjectRead }>(`/projects/${projectId}`);
  return body.data;
}

export async function createProject(payload: ProjectCreatePayload): Promise<ProjectRead> {
  const body = await apiFetch<{ data: ProjectRead }>("/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateProject(
  projectId: string,
  payload: ProjectUpdatePayload,
): Promise<ProjectRead> {
  const body = await apiFetch<{ data: ProjectRead }>(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export type DeliveryDashboardResponse = {
  overview: Record<string, unknown>;
  milestones: Array<Record<string, unknown>>;
  confidence: number;
  risks: Array<Record<string, unknown>>;
  bottlenecks: Array<Record<string, unknown>>;
  traffic_light: "green" | "yellow" | "red";
  daily_summary: string | null;
};

export async function fetchDeliveryDashboard(
  projectId: string,
): Promise<DeliveryDashboardResponse> {
  return apiFetch<DeliveryDashboardResponse>(`/delivery/dashboard/${projectId}`);
}

export type DeliveryPortfolioResponse = {
  projects: Array<{
    project_id: string;
    dashboard: DeliveryDashboardResponse;
  }>;
  milestones: Array<Record<string, unknown>>;
};

export async function fetchDeliveryPortfolio(): Promise<DeliveryPortfolioResponse> {
  return apiFetch<DeliveryPortfolioResponse>("/delivery/portfolio");
}

export type ThroughputSnapshotRead = {
  id: string;
  project_id: string;
  snapshot_date: string;
  units_completed: number;
  units_forecast: number | null;
  rolling_7day_units: number | null;
  created_at: string;
  updated_at: string;
};

export type DeliveryConfidencePoint = {
  id: string;
  project_id: string;
  milestone_id: string;
  score_pct: string;
  forecast_completion_date: string | null;
  status: string;
  model_version: string;
  created_at: string;
};

export type RiskAlertRead = {
  id: string;
  project_id: string;
  milestone_id: string | null;
  alert_type: string;
  risk_tier: "low" | "medium" | "high" | "critical";
  title: string;
  detail: string;
  slippage_probability: string | null;
  contributing_causes: Record<string, number> | null;
  status: string;
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string;
  updated_at: string;
};

export type MilestoneRead = {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  planned_date: string;
  actual_date: string | null;
  status: "pending" | "on_track" | "at_risk" | "completed" | "missed";
};

export async function listProjectThroughput(
  projectId: string,
): Promise<ThroughputSnapshotRead[]> {
  const body = await apiFetch<{ data: ThroughputSnapshotRead[] }>(
    `/projects/${projectId}/throughput?limit=100`,
  );
  return body.data;
}

export async function listProjectDeliveryConfidence(
  projectId: string,
): Promise<DeliveryConfidencePoint[]> {
  const body = await apiFetch<{ data: DeliveryConfidencePoint[] }>(
    `/projects/${projectId}/delivery-confidence?limit=100`,
  );
  return body.data;
}

export async function listProjectRiskAlerts(projectId: string): Promise<RiskAlertRead[]> {
  const body = await apiFetch<{ data: RiskAlertRead[] }>(
    `/projects/${projectId}/risk-alerts`,
  );
  return body.data;
}

export async function listProjectMilestones(projectId: string): Promise<MilestoneRead[]> {
  const body = await apiFetch<{ data: MilestoneRead[] }>(
    `/projects/${projectId}/milestones`,
  );
  return body.data;
}

export async function listProjectTeams(projectId: string): Promise<TeamRead[]> {
  const body = await apiFetch<{ data: TeamRead[] }>(`/projects/${projectId}/teams?limit=100`);
  return body.data;
}

export async function listTeamAnnotators(teamId: string): Promise<AnnotatorRead[]> {
  const body = await apiFetch<{ data: AnnotatorRead[] }>(`/teams/${teamId}/annotators?limit=100`);
  return body.data;
}

export async function listProjectUtilization(
  projectId: string,
  filters: ProjectUtilizationFilters = {},
): Promise<UtilizationSnapshotRead[]> {
  const params = new URLSearchParams();
  if (filters.team_id) params.set("team_id", filters.team_id);
  if (filters.annotator_id) params.set("annotator_id", filters.annotator_id);
  if (filters.from_date) params.set("from_date", filters.from_date);
  if (filters.to_date) params.set("to_date", filters.to_date);
  params.set("limit", String(filters.limit ?? 100));
  const query = params.toString();
  const body = await apiFetch<{ data: UtilizationSnapshotRead[] }>(
    `/projects/${projectId}/utilization?${query}`,
  );
  return body.data;
}

export async function listWorkforceSkills(): Promise<SkillRead[]> {
  const body = await apiFetch<{ data: SkillRead[] }>("/workforce/skills?limit=100");
  return body.data;
}

export async function listProjectSkillRequirements(
  projectId: string,
): Promise<ProjectSkillRequirementRead[]> {
  const body = await apiFetch<{ data: ProjectSkillRequirementRead[] }>(
    `/projects/${projectId}/skill-requirements?limit=100`,
  );
  return body.data;
}

export async function getProjectSkillMatrix(projectId: string): Promise<SkillMatrixRead> {
  const body = await apiFetch<{ data: SkillMatrixRead }>(`/projects/${projectId}/skill-matrix`);
  return body.data;
}

export async function getProjectTrainingGaps(projectId: string): Promise<TrainingGapSummaryRead> {
  const body = await apiFetch<{ data: TrainingGapSummaryRead }>(
    `/projects/${projectId}/training-gaps`,
  );
  return body.data;
}

export async function listProjectCapabilityGaps(
  projectId: string,
): Promise<CapabilityGapRead[]> {
  const body = await apiFetch<{ data: CapabilityGapRead[] }>(
    `/projects/${projectId}/capability-gaps?limit=100`,
  );
  return body.data;
}

export async function detectProjectCapabilityGaps(
  projectId: string,
): Promise<CapabilityGapDetectionResponse> {
  const body = await apiFetch<{ data: CapabilityGapDetectionResponse }>(
    `/projects/${projectId}/capability-gaps/detect`,
    { method: "POST" },
  );
  return body.data;
}

export async function updateCapabilityGap(
  gapId: string,
  payload: CapabilityGapUpdatePayload,
): Promise<CapabilityGapRead> {
  const body = await apiFetch<{ data: CapabilityGapRead }>(`/capability-gaps/${gapId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function deleteCapabilityGap(gapId: string): Promise<void> {
  await apiFetch<void>(`/capability-gaps/${gapId}`, { method: "DELETE" });
}

export async function generateWorkforceRecommendations(
  projectId: string,
): Promise<WorkforceRecommendationGenerateResponse> {
  const body = await apiFetch<{ data: WorkforceRecommendationGenerateResponse }>(
    `/projects/${projectId}/workforce-recommendations/generate`,
    { method: "POST" },
  );
  return body.data;
}

export async function createAgentQuery(payload: AgentQueryCreate): Promise<AgentQueryRead> {
  const body = await apiFetch<{ data: AgentQueryRead }>("/agent-queries", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function createUser(payload: {
  email: string;
  password: string;
  full_name?: string;
  role: AppRole;
  org_id: string;
}): Promise<UserRead> {
  const body = await apiFetch<{ data: UserRead }>("/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateUser(
  userId: string,
  payload: {
    full_name?: string | null;
    role?: AppRole;
    org_id?: string;
    is_active?: boolean;
    password?: string;
  },
): Promise<UserRead> {
  const body = await apiFetch<{ data: UserRead }>(`/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function deleteUser(userId: string): Promise<void> {
  await apiFetch<void>(`/users/${userId}`, { method: "DELETE" });
}

export function defaultRouteForRole(role: AppRole): string {
  switch (role) {
    case "client":
      return "/client";
    case "delivery_manager":
      return "/dashboard";
    case "bsg_leadership":
      return "/leadership";
    case "super_admin":
      return "/admin";
    default:
      return "/login";
  }
}

export function canAccessPath(role: AppRole, path: string): boolean {
  if (path === "/login" || path === "/unauthorized" || path === "/settings") return true;
  if (role === "super_admin") return path.startsWith("/admin");
  if (role === "client") return path.startsWith("/client");
  if (role === "bsg_leadership") return path.startsWith("/leadership");
  return !path.startsWith("/client") && !path.startsWith("/admin");
}

export async function listKnowledgeDocuments(filters: KnowledgeDocumentFilters = {}): Promise<KnowledgeDocumentApi[]> {
  const params = new URLSearchParams();
  if (filters.sourceType) params.set("source_type", filters.sourceType);
  if (filters.owner) params.set("owner", filters.owner);
  if (filters.visibility) params.set("visibility", filters.visibility);
  if (filters.ready !== undefined) params.set("ready", String(filters.ready));
  if (filters.workflowState) params.set("workflow_state", filters.workflowState);
  if (filters.effectiveDateFrom) params.set("effective_date_from", filters.effectiveDateFrom);
  if (filters.effectiveDateTo) params.set("effective_date_to", filters.effectiveDateTo);
  if (filters.semanticQuery) params.set("semantic_query", filters.semanticQuery);
  const query = params.toString();
  const body = await apiFetch<{ data: KnowledgeDocumentApi[] }>(`/knowledge/documents${query ? `?${query}` : ""}`);
  return body.data;
}

export async function getKnowledgeDocument(documentId: string): Promise<KnowledgeDocumentApi> {
  const body = await apiFetch<{ data: KnowledgeDocumentApi }>(`/knowledge/documents/${documentId}`);
  return body.data;
}

export async function listKnowledgeFolders(): Promise<KnowledgeFolderApi[]> {
  const body = await apiFetch<{ data: KnowledgeFolderApi[] }>("/knowledge/folders");
  return body.data;
}

export async function createKnowledgeFolder(payload: { name: string }): Promise<KnowledgeFolderApi> {
  const body = await apiFetch<{ data: KnowledgeFolderApi }>("/knowledge/folders", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateKnowledgeDocument(
  documentId: string,
  payload: Record<string, string | undefined>,
): Promise<KnowledgeDocumentApi> {
  const body = await apiFetch<{ data: KnowledgeDocumentApi }>(`/knowledge/documents/${documentId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function deleteKnowledgeDocument(documentId: string): Promise<void> {
  await apiFetch<void>(`/knowledge/documents/${documentId}`, { method: "DELETE" });
}

export async function reindexKnowledgeDocument(documentId: string): Promise<KnowledgeDocumentApi> {
  const body = await apiFetch<{ data: KnowledgeDocumentApi }>(`/knowledge/documents/${documentId}/index`, {
    method: "POST",
  });
  return body.data;
}

export async function downloadKnowledgeDocumentFile(documentId: string): Promise<{ blob: Blob; fileName: string | null }> {
  const response = await fetch(`${API_BASE}/knowledge/documents/${documentId}/download`, {
    method: "GET",
    credentials: "include",
  });
  if (!response.ok) {
    const error = await parseApiError(response);
    throw error;
  }
  const disposition = response.headers.get("Content-Disposition");
  const encodedName = disposition?.match(/filename\*=UTF-8''([^;]+)/)?.[1];
  const quotedName = disposition?.match(/filename="?([^";]+)"?/)?.[1];
  const fileName = encodedName ? decodeURIComponent(encodedName) : quotedName ?? null;
  return { blob: await response.blob(), fileName };
}

export type KnowledgeAskOptions = {
  includeHistories?: boolean;
  maxSources?: number;
  minRelevanceScore?: number;
  project?: string;
  department?: string;
};

export async function askKnowledgeAgent(queryText: string, options: KnowledgeAskOptions = {}): Promise<KnowledgeAskResponseApi> {
  const body = await apiFetch<{ data: KnowledgeAskResponseApi }>("/knowledge/ask", {
    method: "POST",
    body: JSON.stringify({
      query_text: queryText,
      include_histories: options.includeHistories ?? true,
      max_sources: options.maxSources ?? 5,
      min_relevance_score: options.minRelevanceScore ?? 0.25,
      project: options.project || null,
      department: options.department || null,
    }),
  });
  return body.data;
}

export async function uploadKnowledgeDocument(
  file: File,
  fields: Record<string, string>,
): Promise<KnowledgeDocumentApi> {
  const formData = new FormData();
  formData.append("file", file);
  for (const [key, value] of Object.entries(fields)) {
    if (value) formData.append(key, value);
  }
  const body = await apiFetch<{ data: KnowledgeDocumentApi }>("/knowledge/documents", {
    method: "POST",
    body: formData,
  });
  return body.data;
}

export async function listKnowledgeDocumentVersions(documentId: string): Promise<KnowledgeDocumentVersionApi[]> {
  const body = await apiFetch<{ data: KnowledgeDocumentVersionApi[] }>(`/knowledge/documents/${documentId}/versions`);
  return body.data;
}

export async function compareKnowledgeDocumentVersions(
  documentId: string,
  leftVersionId: string,
  rightVersionId: string,
): Promise<KnowledgeVersionCompareApi> {
  const params = new URLSearchParams({
    left_version_id: leftVersionId,
    right_version_id: rightVersionId,
  });
  const body = await apiFetch<{ data: KnowledgeVersionCompareApi }>(
    `/knowledge/documents/${documentId}/versions/compare?${params}`,
  );
  return body.data;
}

export async function getKnowledgeRetrievalSettings(): Promise<KnowledgeRetrievalSettingsApi> {
  const body = await apiFetch<{ data: KnowledgeRetrievalSettingsApi }>("/knowledge/retrieval-settings");
  return body.data;
}

export async function updateKnowledgeRetrievalSettings(
  payload: Partial<KnowledgeRetrievalSettingsApi>,
): Promise<KnowledgeRetrievalSettingsApi> {
  const body = await apiFetch<{ data: KnowledgeRetrievalSettingsApi }>("/knowledge/retrieval-settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}
