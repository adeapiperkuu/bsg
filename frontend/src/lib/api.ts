import type { AppRole, AuthSession, MeUser, OrganisationRead, UserRead } from "@/types/auth";
import type { AgentQueryCreate, AgentQueryRead } from "@/types/workforce";
import type {
  KnowledgeBootstrapApi,
  KnowledgeDocumentApi,
  KnowledgeDocumentAiSummaryApi,
  KnowledgeDocumentApprovalEventApi,
  KnowledgeDocumentSummaryApi,
  KnowledgeDocumentLifecycleActionApi,
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
  KnowledgeLibraryHealthApi,
  KnowledgeRelatedKnowledgeApi,
  KnowledgeRetrievalSettingsApi,
  KnowledgeSuggestionApi,
  KnowledgeVersionCompareApi,
} from "@/types/knowledge";
import type {
  DeliveryChatConversation,
  DeliveryChatConversationSummary,
  DeliveryChatRequest,
  DeliveryChatSource,
} from "@/types/delivery-chat";

function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (import.meta.env.DEV) {
    // Always proxy in dev; localhost:8000 often hits Docker/WSL instead of the FastAPI app.
    if (!configured || configured.includes("localhost:8000") || configured.includes("127.0.0.1:8000")) {
      return "/api/v1";
    }
  }
  return configured || "/api/v1";
}

export const API_BASE = resolveApiBase();

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

let refreshPromise: Promise<boolean> | null = null;

async function refreshAuthSession(): Promise<boolean> {
  refreshPromise ??= (async () => {
    const refreshHeaders = new Headers();
    const csrf = getCsrfToken();
    if (csrf) refreshHeaders.set("X-CSRF-Token", csrf);

    const refreshed = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: refreshHeaders,
      credentials: "include",
    });

    if (refreshed.ok) return true;

    if (refreshed.status === 401 || refreshed.status === 403) {
      resetAuthSession();
    }
    return false;
  })().finally(() => {
    refreshPromise = null;
  });

  return refreshPromise;
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
    if (!getCsrfToken()) {
      resetAuthSession();
      throw error;
    }
    if (await refreshAuthSession()) {
      return apiFetch<T>(path, init, true);
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
    if (!getCsrfToken()) {
      resetAuthSession();
      throw error;
    }
    if (await refreshAuthSession()) {
      return apiFetchBlob(path, init, true);
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
  if (!body?.data || typeof body.data.answer_text !== "string") {
    throw new ApiError(
      500,
      "INVALID_RESPONSE",
      "The workforce agent returned an unexpected response.",
    );
  }
  return {
    ...body.data,
    evidence_links: body.data.evidence_links ?? [],
  };
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

export type QualityPage = {
  dashboard: QualityDashboard;
  calibration_brief: CalibrationBrief;
  sop_ambiguity_flags: SopAmbiguityFlag[];
  reviewer_scorecards: ReviewerScorecard[];
};

export async function fetchQualityPage(projectId: string): Promise<QualityPage> {
  const body = await apiFetch<{ data: QualityPage }>(`/projects/${projectId}/quality-page`);
  return body.data;
}

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

export type OperationalTowerKpis = {
  activeProjects: number;
  scheduleConfidence: number | null;
  openEscalations: number;
  avgQualityScore: number | null;
  totalProjects: number;
};

export type OperationalTower = {
  kpis: OperationalTowerKpis;
  healthDistribution: Array<{ name: string; value: number; color: string }>;
  riskTrend: {
    series: Array<{ name: string; color: string }>;
    data: Array<Record<string, string | number>>;
  };
  qualityTrend: Array<{ week: string; goldAccuracy: number | null; iaa: number | null }>;
  utilization: Array<{ team: string; value: number }>;
  alerts: Array<{ sev: string; project: string; desc: string; ts: string }>;
  recommendations: Array<{
    title: string;
    confidence: number;
    evidence: number;
    priority: string;
  }>;
  milestones: Array<{
    project: string;
    name: string;
    due: string;
    confidence: number | null;
    status: string;
  }>;
  activity: Array<{ ts: string; actor: string; text: string }>;
  criticalEscalations: number;
};

export type ExecutiveSummary = {
  text: string;
  week: string;
  generated_by_ai: boolean;
  status: string;
  approved: boolean;
  updated_at: string | null;
};

export async function fetchOperationalTower(): Promise<OperationalTower> {
  const body = await apiFetch<{ data: OperationalTower }>("/dashboard/operational-tower");
  return body.data;
}

export async function fetchExecutiveSummary(): Promise<ExecutiveSummary | null> {
  const body = await apiFetch<{ data: ExecutiveSummary | null }>("/dashboard/executive-summary");
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

type LegacyKnowledgeBootstrapApi = Partial<KnowledgeBootstrapApi> & {
  documents?: KnowledgeDocumentApi[];
  library_health?: KnowledgeLibraryHealthApi;
};

const DEFAULT_KNOWLEDGE_PERMISSIONS: KnowledgeBootstrapApi["permissions"] = {
  can_upload: true,
  can_manage_eval: true,
  can_adjust_retrieval_scope: true,
};

const EMPTY_KNOWLEDGE_LIBRARY_HEALTH: KnowledgeLibraryHealthApi = {
  ready_count: 0,
  ready_for_retrieval_count: 0,
  approved_and_indexed_count: 0,
  needs_review_count: 0,
  expired_count: 0,
  needs_reindex_count: 0,
  failed_processing_count: 0,
  missing_metadata_count: 0,
  indexing_count: 0,
  draft_count: 0,
  archived_count: 0,
  approaching_expiry_count: 0,
  outdated_count: 0,
};

function toDocumentSummary(doc: KnowledgeDocumentApi): KnowledgeDocumentSummaryApi {
  return {
    id: doc.id,
    folder_id: doc.folder_id,
    folder_name: doc.folder_name,
    folder_kind: doc.folder_kind,
    title: doc.title,
    source_type: doc.source_type,
    version: doc.version,
    visibility: doc.visibility,
    status: doc.status,
    owner_approver: doc.owner_approver,
    effective_date: doc.effective_date,
    expiry_date: doc.expiry_date,
    submitted_at: doc.submitted_at,
    reviewed_at: doc.reviewed_at,
    approved_at: doc.approved_at,
    rejection_reason: doc.rejection_reason,
    file_name: doc.file_name,
    processing_status: doc.processing_status,
    processing_error: doc.processing_error,
    indexing_status: doc.indexing_status,
    workflow_state: doc.workflow_state,
    retrieval_ready: doc.retrieval_ready,
    retrieval_readiness_reason: doc.retrieval_readiness_reason,
    retrieval_action: doc.retrieval_action,
    updated_at: doc.updated_at,
  };
}

function buildBootstrapFromDocuments(
  folders: KnowledgeFolderApi[],
  documents: KnowledgeDocumentApi[],
  libraryHealth?: KnowledgeLibraryHealthApi,
): KnowledgeBootstrapApi {
  const byFolderId = documents.reduce<Record<string, number>>((acc, doc) => {
    acc[doc.folder_id] = (acc[doc.folder_id] ?? 0) + 1;
    return acc;
  }, {});
  return {
    folders,
    folder_tree: folders.map((folder) => ({
      ...folder,
      document_count: byFolderId[folder.id] ?? 0,
    })),
    recent_documents: documents.slice(0, 30).map(toDocumentSummary),
    document_counts: {
      total: documents.length,
      by_folder_id: byFolderId,
    },
    permissions: DEFAULT_KNOWLEDGE_PERMISSIONS,
    library_health: {
      ready_count:
        libraryHealth?.ready_for_retrieval_count ??
        libraryHealth?.ready_count ??
        documents.filter((d) => d.retrieval_ready).length,
      ready_for_retrieval_count:
        libraryHealth?.ready_for_retrieval_count ??
        libraryHealth?.ready_count ??
        documents.filter((d) => d.retrieval_ready).length,
      approved_and_indexed_count:
        libraryHealth?.approved_and_indexed_count ??
        documents.filter((d) => d.status === "approved" && d.indexing_status === "indexed").length,
      needs_review_count:
        libraryHealth?.needs_review_count ??
        documents.filter((d) => d.workflow_state === "needs_review").length,
      expired_count:
        libraryHealth?.expired_count ?? documents.filter((d) => d.workflow_state === "expired").length,
      needs_reindex_count:
        libraryHealth?.needs_reindex_count ??
        documents.filter((d) => d.workflow_state === "needs_reindex").length,
      failed_processing_count:
        libraryHealth?.failed_processing_count ??
        documents.filter(
          (d) => d.processing_status === "failed" || d.indexing_status === "failed",
        ).length,
      missing_metadata_count:
        libraryHealth?.missing_metadata_count ??
        documents.filter((d) => !d.owner_approver?.trim() || !d.effective_date).length,
      indexing_count: libraryHealth?.indexing_count ?? 0,
      draft_count: libraryHealth?.draft_count ?? documents.filter((d) => d.status === "draft").length,
      archived_count:
        libraryHealth?.archived_count ?? documents.filter((d) => d.status === "archived").length,
      approaching_expiry_count: libraryHealth?.approaching_expiry_count ?? 0,
      outdated_count: libraryHealth?.outdated_count ?? 0,
    },
  };
}

function normalizeKnowledgeBootstrap(data: LegacyKnowledgeBootstrapApi): KnowledgeBootstrapApi {
  if (data.recent_documents && data.document_counts) {
    return {
      folders: data.folders ?? [],
      folder_tree:
        data.folder_tree ??
        (data.folders ?? []).map((folder) => ({
          ...folder,
          document_count: data.document_counts?.by_folder_id?.[folder.id] ?? 0,
        })),
      recent_documents: data.recent_documents,
      document_counts: data.document_counts,
      permissions: data.permissions ?? DEFAULT_KNOWLEDGE_PERMISSIONS,
      library_health: {
        ready_count: data.library_health?.ready_for_retrieval_count ?? data.library_health?.ready_count ?? 0,
        ready_for_retrieval_count:
          data.library_health?.ready_for_retrieval_count ?? data.library_health?.ready_count ?? 0,
        approved_and_indexed_count: data.library_health?.approved_and_indexed_count ?? 0,
        needs_review_count: data.library_health?.needs_review_count ?? 0,
        expired_count: data.library_health?.expired_count ?? 0,
        needs_reindex_count: data.library_health?.needs_reindex_count ?? 0,
        failed_processing_count: data.library_health?.failed_processing_count ?? 0,
        missing_metadata_count: data.library_health?.missing_metadata_count ?? 0,
        indexing_count: data.library_health?.indexing_count ?? 0,
        draft_count: data.library_health?.draft_count ?? 0,
        archived_count: data.library_health?.archived_count ?? 0,
        approaching_expiry_count: data.library_health?.approaching_expiry_count ?? 0,
        outdated_count: data.library_health?.outdated_count ?? 0,
      },
    };
  }

  const folders = data.folders ?? [];
  const documents = data.documents ?? [];
  return buildBootstrapFromDocuments(folders, documents, data.library_health);
}

export async function getKnowledgeBootstrap(): Promise<KnowledgeBootstrapApi> {
  try {
    const body = await apiFetch<{ data: LegacyKnowledgeBootstrapApi }>("/knowledge/bootstrap");
    return normalizeKnowledgeBootstrap(body.data);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      const [folders, documents] = await Promise.all([
        listKnowledgeFolders(),
        listKnowledgeDocuments(),
      ]);
      return buildBootstrapFromDocuments(folders, documents);
    }
    throw error;
  }
}

export async function getKnowledgeLibraryHealth(): Promise<KnowledgeLibraryHealthApi> {
  try {
    const body = await apiFetch<{ data: KnowledgeLibraryHealthApi }>("/knowledge/library-health");
    return body.data;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      const bootstrap = await getKnowledgeBootstrap();
      return {
        ...EMPTY_KNOWLEDGE_LIBRARY_HEALTH,
        ...bootstrap.library_health,
      };
    }
    throw error;
  }
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
    {
      headers: filters.aiRank ? { "X-BSG-User-Action": "true" } : undefined,
    },
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

async function postKnowledgeDocumentLifecycleAction(
  documentId: string,
  action: "submit" | "approve" | "reject" | "return-to-draft" | "archive" | "restore",
  payload: KnowledgeDocumentLifecycleActionApi = {},
): Promise<KnowledgeDocumentApi> {
  const body = await apiFetch<{ data: KnowledgeDocumentApi }>(
    `/knowledge/documents/${documentId}/${action}`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
  return body.data;
}

export function submitKnowledgeDocument(
  documentId: string,
  payload?: KnowledgeDocumentLifecycleActionApi,
): Promise<KnowledgeDocumentApi> {
  return postKnowledgeDocumentLifecycleAction(documentId, "submit", payload);
}

export function approveKnowledgeDocument(
  documentId: string,
  payload?: KnowledgeDocumentLifecycleActionApi,
): Promise<KnowledgeDocumentApi> {
  return postKnowledgeDocumentLifecycleAction(documentId, "approve", payload);
}

export function rejectKnowledgeDocument(
  documentId: string,
  payload: KnowledgeDocumentLifecycleActionApi,
): Promise<KnowledgeDocumentApi> {
  return postKnowledgeDocumentLifecycleAction(documentId, "reject", payload);
}

export function returnKnowledgeDocumentToDraft(
  documentId: string,
  payload?: KnowledgeDocumentLifecycleActionApi,
): Promise<KnowledgeDocumentApi> {
  return postKnowledgeDocumentLifecycleAction(documentId, "return-to-draft", payload);
}

export function archiveKnowledgeDocument(
  documentId: string,
  payload?: KnowledgeDocumentLifecycleActionApi,
): Promise<KnowledgeDocumentApi> {
  return postKnowledgeDocumentLifecycleAction(documentId, "archive", payload);
}

export function restoreKnowledgeDocument(
  documentId: string,
  payload?: KnowledgeDocumentLifecycleActionApi,
): Promise<KnowledgeDocumentApi> {
  return postKnowledgeDocumentLifecycleAction(documentId, "restore", payload);
}

export async function listKnowledgeDocumentApprovalHistory(
  documentId: string,
): Promise<KnowledgeDocumentApprovalEventApi[]> {
  const body = await apiFetch<{ data: KnowledgeDocumentApprovalEventApi[] }>(
    `/knowledge/documents/${documentId}/approval-history`,
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

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

function sanitizeKnowledgeConversationHistory(
  history: KnowledgeConversationHistoryTurnApi[] = [],
): KnowledgeConversationHistoryTurnApi[] {
  return history
    .filter((turn) => turn.content.trim().length > 0)
    .slice(-6)
    .map((turn) => ({
      role: turn.role,
      content: turn.content.trim(),
    }));
}

function knowledgeConversationId(value: string | null | undefined): string | undefined {
  if (!value || !isUuid(value)) return undefined;
  return value;
}

export async function askKnowledgeAgent(
  queryText: string,
  options: KnowledgeAskOptions = {},
): Promise<KnowledgeAskResponseApi> {
  const payload: Record<string, unknown> = {
    query_text: queryText.trim(),
    conversation_history: sanitizeKnowledgeConversationHistory(options.conversationHistory),
  };
  if (options.answerMode !== undefined) {
    payload.answer_mode = options.answerMode;
  }
  const conversationId = knowledgeConversationId(options.conversationId);
  if (conversationId) {
    payload.conversation_id = conversationId;
  }
  const body = await apiFetch<{ data: KnowledgeAskResponseApi }>("/knowledge/ask", {
    method: "POST",
    headers: { "X-BSG-User-Action": "true" },
    body: JSON.stringify(payload),
  });
  return body.data;
}

export type KnowledgeStreamEvent =
  | { type: "meta"; query_id?: string; confidence_estimate: number }
  | { type: "accepted" }
  | { type: "searching_sources" }
  | { type: "sources_found"; source_count: number; eligible_doc_count?: number }
  | { type: "generating_answer" }
  | { type: "validating_grounding" }
  | { type: "status"; phase: "searching" | "reading" | "generating" }
  | { type: "delta"; text: string }
  | { type: "answer_delta"; text: string }
  | { type: "replace"; text: string }
  | { type: "final"; query_id?: string | null; conversation_id?: string | null; answer_text: string; confidence_score: number; confidence_band?: string | null; confidence_reasons: string[]; next_step: string; structured_answer: KnowledgeAskResponseApi["structured_answer"]; model_used: string | null; retrieval_debug?: KnowledgeAskResponseApi["retrieval_debug"] }
  | { type: "done"; query_id?: string | null; conversation_id?: string | null; answer_text: string; confidence_score: number; confidence_band?: string | null; confidence_reasons: string[]; next_step: string; structured_answer: KnowledgeAskResponseApi["structured_answer"]; model_used: string | null; retrieval_debug?: KnowledgeAskResponseApi["retrieval_debug"] }
  | { type: "error"; message: string; code?: string; retryable?: boolean };

export async function* streamKnowledgeAsk(
  queryText: string,
  options: KnowledgeAskOptions = {},
): AsyncGenerator<KnowledgeStreamEvent> {
  const payload: Record<string, unknown> = {
    query_text: queryText.trim(),
    conversation_history: sanitizeKnowledgeConversationHistory(options.conversationHistory),
  };
  if (options.answerMode !== undefined) payload.answer_mode = options.answerMode;
  const conversationId = knowledgeConversationId(options.conversationId);
  if (conversationId) payload.conversation_id = conversationId;

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
    const err = (await response.json().catch(() => ({}))) as {
      error?: { code?: string; message?: string; details?: { errors?: unknown } };
    };
    const detail =
      err.error?.code === "VALIDATION_ERROR"
        ? "The request was rejected by the server. Try starting a new chat."
        : (err.error?.message ?? "Stream request failed.");
    throw new ApiError(response.status, err.error?.code ?? "API_ERROR", detail);
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

export async function getKnowledgeQueryAnswer(queryId: string): Promise<KnowledgeAskResponseApi> {
  const body = await apiFetch<{ data: KnowledgeAskResponseApi }>(`/knowledge/queries/${queryId}`);
  return body.data;
}

export async function listKnowledgeConversations(
  limit = 30,
): Promise<KnowledgeConversationSummaryApi[]> {
  const body = await apiFetch<{ data: KnowledgeConversationSummaryApi[] }>(
    `/knowledge/conversations?limit=${limit}`,
  );
  return body.data;
}

export async function getKnowledgeConversation(
  conversationId: string,
): Promise<KnowledgeConversationApi> {
  const body = await apiFetch<{ data: KnowledgeConversationApi }>(
    `/knowledge/conversations/${conversationId}`,
  );
  return body.data;
}

export async function listAgentQueries(limit = 20): Promise<AgentQueryApi[]> {
  const body = await apiFetch<{ data: AgentQueryApi[] }>(`/agent-queries?limit=${limit}`);
  return body.data;
}

export async function submitKnowledgeFeedback(
  payload: KnowledgeFeedbackRequestApi,
): Promise<KnowledgeFeedbackResponseApi> {
  const body = await apiFetch<{ data: KnowledgeFeedbackResponseApi }>("/knowledge/feedback", {
    method: "POST",
    body: JSON.stringify({
      query_id: payload.query_id,
      rating: payload.rating,
      comment: payload.comment ?? null,
      feedback_reason: payload.feedback_reason ?? null,
    }),
  });
  return body.data;
}

export async function listKnowledgeSuggestions(status?: string): Promise<KnowledgeSuggestionApi[]> {
  const params = status ? `?status=${encodeURIComponent(status)}` : "";
  const body = await apiFetch<{ data: KnowledgeSuggestionApi[] }>(`/knowledge/suggestions${params}`);
  return body.data;
}

export async function generateKnowledgeSuggestions(documentId?: string): Promise<KnowledgeSuggestionApi[]> {
  const params = documentId ? `?document_id=${encodeURIComponent(documentId)}` : "";
  const body = await apiFetch<{ data: KnowledgeSuggestionApi[] }>(`/knowledge/suggestions/generate${params}`, {
    method: "POST",
  });
  return body.data;
}

export async function applyKnowledgeSuggestion(suggestionId: string): Promise<KnowledgeSuggestionApi> {
  const body = await apiFetch<{ data: KnowledgeSuggestionApi }>(
    `/knowledge/suggestions/${suggestionId}/apply`,
    { method: "POST" },
  );
  return body.data;
}

export async function dismissKnowledgeSuggestion(suggestionId: string): Promise<KnowledgeSuggestionApi> {
  const body = await apiFetch<{ data: KnowledgeSuggestionApi }>(
    `/knowledge/suggestions/${suggestionId}/dismiss`,
    { method: "POST" },
  );
  return body.data;
}

export async function getKnowledgeRelatedDocuments(
  documentId: string,
): Promise<KnowledgeRelatedKnowledgeApi> {
  const body = await apiFetch<{ data: KnowledgeRelatedKnowledgeApi }>(
    `/knowledge/documents/${documentId}/related`,
  );
  return body.data;
}

export async function generateKnowledgeDocumentSummary(
  documentId: string,
): Promise<KnowledgeDocumentAiSummaryApi> {
  const body = await apiFetch<{ data: KnowledgeDocumentAiSummaryApi }>(
    `/knowledge/documents/${documentId}/summary`,
    { method: "POST" },
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
  getProjectWorkforceDashboard,
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
