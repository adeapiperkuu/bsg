import type { AppRole, AuthSession, MeUser, OrganisationRead, UserRead } from "@/types/auth";
import type { AgentQueryCreate, AgentQueryRead } from "@/types/workforce";
import type {
  KnowledgeBootstrapApi,
  KnowledgeDocumentApi,
  KnowledgeDocumentSummaryApi,
  KnowledgeAskResponseApi,
  KnowledgeAnswerModeApi,
  AgentQueryApi,
  KnowledgeConversationApi,
  KnowledgeConversationSummaryApi,
  KnowledgeConversationHistoryTurnApi,
  KnowledgeDocumentFilters,
  KnowledgeDocumentVersionApi,
  KnowledgeFeedbackRequestApi,
  KnowledgeFeedbackResponseApi,
  KnowledgeFolderApi,
  KnowledgeGapTodoApi,
  KnowledgeLibraryHealthApi,
  KnowledgeRetrievalSettingsApi,
  KnowledgeVersionCompareApi,
} from "@/types/knowledge";
import type {
  DeliveryChatConversation,
  DeliveryChatConversationSummary,
  DeliveryChatRequest,
  DeliveryChatSource,
} from "@/types/delivery-chat";

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

/** Display labels for quality error taxonomy codes (spec §7.3). */
export const ERROR_CATEGORY_LABELS: Record<string, string> = {
  "ERR-01": "Boundary precision",
  "ERR-02": "Class confusion",
  "ERR-03": "Missed object",
  "ERR-04": "Guideline ambiguity",
  "ERR-05": "False positive",
  "ERR-06": "Attribute error",
  "ERR-07": "Tool error",
  "ERR-OTHER": "Other",
};

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

function clearSessionHintCookie() {
  if (typeof document === "undefined") return;
  document.cookie = "csrf_token=; Max-Age=0; path=/; SameSite=Lax";
}

function clearClientAuthState() {
  if (typeof window === "undefined") return;
  void import("@/stores/useAuthStore").then(({ useAuthStore }) => {
    useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false });
  });
}

/** Clear stale browser session hints after auth failure (invalid/expired session or wrong API). */
export function resetAuthSession() {
  clearSessionHintCookie();
  clearClientAuthState();
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
    const refreshed = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) {
      return apiFetch<T>(path, init, true);
    }
    if (refreshed.status === 401) {
      resetAuthSession();
    }
    throw error;
  }

  return parseResponse<T>(response);
}

export async function apiFetchBlob(
  path: string,
  init: RequestInit = {},
  retried = false,
): Promise<Blob> {
  const headers = new Headers(init.headers);
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 401 && !path.startsWith("/auth/") && !retried) {
    const error = await parseApiError(response);
    const refreshed = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) {
      return apiFetchBlob(path, init, true);
    }
    if (refreshed.status === 401) {
      resetAuthSession();
    }
    throw error;
  }

  if (!response.ok) {
    throw await parseApiError(response);
  }
  return response.blob();
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

const SESSION_REQUEST_TIMEOUT_MS = 15_000;

export async function fetchMe(timeoutMs = SESSION_REQUEST_TIMEOUT_MS): Promise<MeUser> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = setTimeout(
      () => reject(new ApiError(408, "SESSION_TIMEOUT", "Session request timed out.")),
      timeoutMs,
    );
  });
  try {
    const body = await Promise.race([apiFetch<{ data: MeUser }>("/me"), timeout]);
    return body.data;
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId);
  }
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

export async function listProjectThroughput(projectId: string): Promise<ThroughputSnapshotRead[]> {
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
  const body = await apiFetch<{ data: RiskAlertRead[] }>(`/projects/${projectId}/risk-alerts`);
  return body.data;
}

export async function listProjectMilestones(projectId: string): Promise<MilestoneRead[]> {
  const body = await apiFetch<{ data: MilestoneRead[] }>(`/projects/${projectId}/milestones`);
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

export type QualityDashboard = {
  kpis: {
    gold_set_accuracy_pct: number | null;
    iaa_krippendorff_alpha: number | null;
    rework_rate_pct: number | null;
    rework_rate_target_pct: number | null;
    active_drift_alerts: number;
  };
  trend: Array<{
    iso_year: number;
    iso_week: number;
    gold_set_accuracy_pct: number | null;
    iaa_krippendorff_alpha: number | null;
  }>;
  error_breakdown: Array<{ error_category: string; share_pct: number }>;
  team_scorecard: Array<{
    team_id: string;
    team_name: string;
    gold_set_accuracy_pct: number | null;
    iaa_krippendorff_alpha: number | null;
    rework_rate_pct: number | null;
    status: string;
    has_drift_alert: boolean;
    has_data_gap?: boolean;
    evaluated_item_count?: number | null;
  }>;
  drift_alerts: Array<{
    id: string;
    title: string;
    detail: string;
    risk_tier: string;
    status: string;
  }>;
  narrative: string | null;
  data_gap_teams: string[];
};

export type AdminProject = {
  id: string;
  name: string;
  org_id: string;
  org_name: string;
  status: string;
  vertical: string;
  start_date: string;
  target_end_date: string;
  latest_iso_year: number | null;
  latest_iso_week: number | null;
  active_drift_alerts: number;
  data_gap_teams: string[];
};

export type QualityScanRunProjectResult = {
  project_id: string;
  name: string;
  snapshots: number;
  alerts: number;
  data_gaps: number;
  teams: Array<{
    team_id: string;
    has_drift: boolean;
    data_gap: boolean;
    detail: string | null;
  }>;
};

export type QualityScanRun = {
  id: string;
  trigger: "scheduler" | "manual";
  triggered_by: string | null;
  iso_year: number;
  iso_week: number;
  status: "running" | "completed" | "failed";
  started_at: string;
  finished_at: string | null;
  projects_scanned: number;
  snapshots_evaluated: number;
  alerts_created: number;
  data_gaps: number;
  per_project_results: QualityScanRunProjectResult[] | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export async function listAdminProjects(): Promise<AdminProject[]> {
  const body = await apiFetch<{ data: AdminProject[] }>("/internal/projects");
  return body.data;
}

export async function listQualityScanRuns(): Promise<QualityScanRun[]> {
  const body = await apiFetch<{ data: QualityScanRun[] }>("/internal/quality-scan-runs");
  return body.data;
}

export async function triggerQualityScan(): Promise<QualityScanRun> {
  const body = await apiFetch<{ data: QualityScanRun }>("/internal/quality-scan", { method: "POST" });
  return body.data;
}

export type ThroughputSnapshot = {
  id: string;
  project_id: string;
  snapshot_date: string;
  units_completed: number;
  units_forecast: number | null;
  rolling_7day_units: number | null;
};

export type QualityPortfolioProject = {
  project_id: string;
  name: string;
  org_name: string;
  status: string;
  active_drift_alerts: number;
  latest_gold_accuracy: string | null;
  data_gap: boolean;
};

export type QualityPortfolio = {
  portfolio_week: string;
  projects_total: number;
  projects_with_drift: number;
  blended_gold_accuracy: string | null;
  blended_rework_rate: string | null;
  per_project: QualityPortfolioProject[];
};

export async function fetchThroughput(projectId: string): Promise<ThroughputSnapshot[]> {
  const body = await apiFetch<{ data: ThroughputSnapshot[] }>(`/projects/${projectId}/throughput`);
  return body.data;
}

export async function fetchRiskAlerts(projectId: string): Promise<RiskAlertRead[]> {
  const body = await apiFetch<{ data: RiskAlertRead[] }>(`/projects/${projectId}/risk-alerts`);
  return body.data;
}

export async function fetchQualityPortfolio(): Promise<QualityPortfolio> {
  const body = await apiFetch<{ data: QualityPortfolio }>("/leadership/quality-portfolio");
  return body.data;
}

export type CalibrationCandidate = {
  annotator_id: string;
  accuracy_pct: number | null;
  items_evaluated: number;
  error_category: string | null;
  priority: string;
  reason: string;
};

export type CalibrationBrief = {
  project_id: string;
  iso_year: number;
  iso_week: number;
  candidates: CalibrationCandidate[];
  brief_text: string | null;
  signal_sent_at: string | null;
};

export type SopAmbiguityFlag = {
  alert_id: string | null;
  task_type: string | null;
  affected_reviewer_count: number;
  sop_version: string | null;
  draft_amendment: string | null;
  detail: string | null;
};

export type ReviewerScorecard = {
  id: string;
  annotator_id: string;
  project_id: string;
  iso_year: number;
  iso_week: number;
  items_evaluated: number;
  accuracy_pct: number | null;
  error_breakdown: Record<string, number> | null;
};

export async function fetchCalibrationBrief(projectId: string): Promise<CalibrationBrief> {
  const body = await apiFetch<{ data: CalibrationBrief }>(`/projects/${projectId}/calibration-brief`);
  return body.data;
}

export async function fetchSopAmbiguityFlags(projectId: string): Promise<SopAmbiguityFlag[]> {
  const body = await apiFetch<{ data: SopAmbiguityFlag[] }>(`/projects/${projectId}/sop-ambiguity-flags`);
  return body.data;
}

export async function fetchReviewerScorecards(
  projectId: string,
  isoYear?: number,
  isoWeek?: number,
): Promise<ReviewerScorecard[]> {
  const params = new URLSearchParams();
  if (isoYear != null) params.set("iso_year", String(isoYear));
  if (isoWeek != null) params.set("iso_week", String(isoWeek));
  const qs = params.toString();
  const body = await apiFetch<{ data: ReviewerScorecard[] }>(
    `/projects/${projectId}/reviewer-scorecards${qs ? `?${qs}` : ""}`,
  );
  return body.data;
}

export async function resolveRiskAlert(alertId: string, resolutionSummary?: string): Promise<RiskAlertRead> {
  const body = await apiFetch<{ data: RiskAlertRead }>(`/risk-alerts/${alertId}/resolve`, {
    method: "PATCH",
    body: JSON.stringify({ resolution_summary: resolutionSummary ?? null }),
  });
  return body.data;
}

export async function fetchQualityDashboard(projectId: string): Promise<QualityDashboard> {
  const body = await apiFetch<{ data: QualityDashboard }>(`/projects/${projectId}/quality-dashboard`);
  return body.data;
}

export async function postAgentQuery(payload: {
  agent_name: string;
  project_id?: string;
  query_text: string;
}): Promise<AgentQueryRead> {
  const body = await apiFetch<{ data: AgentQueryRead }>("/agent-queries", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
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

function isClientPortalPath(path: string): boolean {
  return path === "/client" || path.startsWith("/client/");
}

export function canAccessPath(role: AppRole, path: string): boolean {
  if (path === "/login" || path === "/unauthorized" || path === "/settings") return true;
  if (role === "super_admin") return path.startsWith("/admin");
  if (role === "client") return isClientPortalPath(path);
  if (role === "bsg_leadership") return path.startsWith("/leadership");
  return !isClientPortalPath(path) && !path.startsWith("/admin");
}

export async function listKnowledgeDocuments(
  filters: KnowledgeDocumentFilters = {},
): Promise<KnowledgeDocumentApi[]> {
  const params = new URLSearchParams();
  if (filters.sourceType) params.set("source_type", filters.sourceType);
  if (filters.owner) params.set("owner", filters.owner);
  if (filters.visibility) params.set("visibility", filters.visibility);
  if (filters.ready !== undefined) params.set("ready", String(filters.ready));
  if (filters.workflowState) params.set("workflow_state", filters.workflowState);
  if (filters.effectiveDateFrom) params.set("effective_date_from", filters.effectiveDateFrom);
  if (filters.effectiveDateTo) params.set("effective_date_to", filters.effectiveDateTo);
  if (filters.semanticQuery) params.set("semantic_query", filters.semanticQuery);
  if (filters.aiRank) params.set("ai_rank", "true");
  const query = params.toString();
  const body = await apiFetch<{ data: KnowledgeDocumentApi[] }>(
    `/knowledge/documents${query ? `?${query}` : ""}`,
  );
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

export async function createKnowledgeFolder(payload: {
  name: string;
}): Promise<KnowledgeFolderApi> {
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
  const body = await apiFetch<{ data: KnowledgeDocumentApi }>(
    `/knowledge/documents/${documentId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export async function deleteKnowledgeDocument(documentId: string): Promise<void> {
  await apiFetch<void>(`/knowledge/documents/${documentId}`, { method: "DELETE" });
}

export async function reindexKnowledgeDocument(documentId: string): Promise<KnowledgeDocumentApi> {
  const body = await apiFetch<{ data: KnowledgeDocumentApi }>(
    `/knowledge/documents/${documentId}/index`,
    {
      method: "POST",
    },
  );
  return body.data;
}

export async function downloadKnowledgeDocumentFile(
  documentId: string,
): Promise<{ blob: Blob; fileName: string | null }> {
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
  const fileName = encodedName ? decodeURIComponent(encodedName) : (quotedName ?? null);
  return { blob: await response.blob(), fileName };
}

export type KnowledgeAskOptions = {
  conversationHistory?: KnowledgeConversationHistoryTurnApi[];
  answerMode?: KnowledgeAnswerModeApi;
  conversationId?: string | null;
};

export async function askKnowledgeAgent(
  queryText: string,
  options: KnowledgeAskOptions = {},
): Promise<KnowledgeAskResponseApi> {
  const body = await apiFetch<{ data: KnowledgeAskResponseApi }>("/knowledge/ask", {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
    body: JSON.stringify(payload),
  });
  return body.data;
}

export type KnowledgeStreamEvent =
  | { type: "meta"; query_id?: string; confidence_estimate: number }
  | { type: "status"; phase: "searching" | "reading" | "generating" }
  | { type: "delta"; text: string }
  | { type: "replace"; text: string }
  | { type: "done"; query_id?: string | null; conversation_id?: string | null; answer_text: string; confidence_score: number; confidence_reasons: string[]; next_step: string; structured_answer: KnowledgeAskResponseApi["structured_answer"]; model_used: string | null; retrieval_debug?: KnowledgeAskResponseApi["retrieval_debug"] }
  | { type: "error"; message: string };

export async function* streamKnowledgeAsk(
  queryText: string,
  options: KnowledgeAskOptions = {},
): AsyncGenerator<KnowledgeStreamEvent> {
  const payload: Record<string, unknown> = {
    query_text: queryText,
    conversation_history: options.conversationHistory ?? [],
  };
  if (options.answerMode !== undefined) payload.answer_mode = options.answerMode;
  if (options.conversationId) payload.conversation_id = options.conversationId;

  const headers = new Headers({ "Content-Type": "application/json", "X-BSG-User-Action": "true" });
  const csrf = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/)?.[1];
  if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));

  const response = await fetch(`${API_BASE}/knowledge/ask/stream`, {
    method: "POST",
    headers,
    credentials: "include",
    body: JSON.stringify(payload),
  });

  if (!response.ok || !response.body) {
    const err = await response.json().catch(() => ({})) as { error?: { code?: string; message?: string } };
    throw new ApiError(response.status, err.error?.code ?? "API_ERROR", err.error?.message ?? "Stream request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  const parseSseLine = (line: string): KnowledgeStreamEvent | null => {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data: ")) return null;
    const raw = trimmed.slice(6).trim();
    if (!raw) return null;
    try {
      return JSON.parse(raw) as KnowledgeStreamEvent;
    } catch {
      return null;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split(/\r?\n/);
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseSseLine(line);
      if (event) yield event;
    }
  }

  if (buf.trim()) {
    const event = parseSseLine(buf);
    if (event) yield event;
  }
}

export type DeliveryChatStreamEvent =
  | { type: "delta"; text: string }
  | { type: "done"; answer: string; sources: DeliveryChatSource[]; conversation_id: string };

export async function* streamDeliveryChatMessage(
  payload: DeliveryChatRequest,
): AsyncGenerator<DeliveryChatStreamEvent> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const csrf = getCsrfToken();
  if (csrf) headers.set("X-CSRF-Token", csrf);

  const response = await fetch(`${API_BASE}/delivery/chat/stream`, {
    method: "POST",
    headers,
    credentials: "include",
    body: JSON.stringify({
      message: payload.message,
      project_id: payload.project_id ?? null,
      conversation_id: payload.conversation_id ?? null,
    }),
  });

  if (!response.ok || !response.body) {
    throw await parseApiError(response);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  const parseLine = (line: string): DeliveryChatStreamEvent | null => {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data: ")) return null;
    const raw = trimmed.slice(6).trim();
    if (!raw) return null;
    try {
      return JSON.parse(raw) as DeliveryChatStreamEvent;
    } catch {
      return null;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split(/\r?\n/);
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseLine(line);
      if (event) yield event;
    }
  }

  if (buf.trim()) {
    const event = parseLine(buf);
    if (event) yield event;
  }
}

export async function getDeliveryChatConversation(
  conversationId: string,
): Promise<DeliveryChatConversation> {
  const body = await apiFetch<{ data: DeliveryChatConversation }>(
    `/delivery/chat/conversations/${conversationId}`,
  );
  return body.data;
}

export async function listDeliveryConversations(
  projectId?: string | null,
): Promise<DeliveryChatConversationSummary[]> {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  const query = params.toString();
  const body = await apiFetch<{ data: DeliveryChatConversationSummary[] }>(
    `/delivery/chat/conversations${query ? `?${query}` : ""}`,
  );
  return body.data;
}

export async function createDeliveryConversation(
  projectId?: string | null,
  title?: string,
): Promise<DeliveryChatConversationSummary> {
  const body = await apiFetch<{ data: DeliveryChatConversationSummary }>(
    "/delivery/chat/conversations",
    {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId ?? null,
        title: title ?? null,
      }),
    },
  );
  return body.data;
}

export async function renameDeliveryConversation(
  conversationId: string,
  title: string,
): Promise<DeliveryChatConversationSummary> {
  const body = await apiFetch<{ data: DeliveryChatConversationSummary }>(
    `/delivery/chat/conversations/${conversationId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    },
  );
  return body.data;
}

export async function deleteDeliveryConversation(conversationId: string): Promise<void> {
  await apiFetch<void>(`/delivery/chat/conversations/${conversationId}`, {
    method: "DELETE",
  });
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

export async function listKnowledgeDocumentVersions(
  documentId: string,
): Promise<KnowledgeDocumentVersionApi[]> {
  const body = await apiFetch<{ data: KnowledgeDocumentVersionApi[] }>(
    `/knowledge/documents/${documentId}/versions`,
  );
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
  const body = await apiFetch<{ data: KnowledgeRetrievalSettingsApi }>(
    "/knowledge/retrieval-settings",
  );
  return body.data;
}

export async function updateKnowledgeRetrievalSettings(
  payload: Partial<KnowledgeRetrievalSettingsApi>,
): Promise<KnowledgeRetrievalSettingsApi> {
  const body = await apiFetch<{ data: KnowledgeRetrievalSettingsApi }>(
    "/knowledge/retrieval-settings",
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export {
  createAnnotatorSkill,
  createEmployeeCertification,
  createProjectSkillRequirement,
  createProjectTeam,
  createTeamAnnotator,
  createTrainingRecord,
  createUtilizationSnapshot,
  deleteAnnotator,
  deleteAnnotatorSkill,
  deleteCapabilityGap,
  deleteEmployeeCertification,
  deleteProjectSkillRequirement,
  deleteTeam,
  deleteTrainingRecord,
  deleteUtilizationSnapshot,
  detectProjectCapabilityGaps,
  generateWorkforceRecommendations,
  getProjectSkillMatrix,
  getProjectTrainingGaps,
  getProjectWorkforceSummary,
  listAnnotatorCertifications,
  listAnnotatorSkills,
  listAnnotatorTrainingRecords,
  listProjectCapabilityGaps,
  listProjectSkillRequirements,
  listProjectTeams,
  listProjectUtilization,
  listTeamAnnotators,
  listWorkforceCertifications,
  listWorkforceSkills,
  listWorkforceTrainingPrograms,
  updateAnnotator,
  updateAnnotatorSkill,
  updateCapabilityGap,
  updateTeam,
  updateEmployeeCertification,
  updateProjectSkillRequirement,
  updateTrainingRecord,
  updateUtilizationSnapshot,
} from "./api/workforce";
