import type { AppRole, AuthSession, MeUser, OrganisationRead, UserRead } from "@/types/auth";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

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
    throw new ApiError(response.status, err?.code ?? "API_ERROR", err?.message ?? "Request failed.");
  }
  return body as T;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
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
    const refreshed = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) {
      return apiFetch<T>(path, init, true);
    }
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

export async function listProjects(): Promise<ProjectRead[]> {
  const body = await apiFetch<{ data: ProjectRead[] }>("/projects");
  return body.data;
}

export type QualityDashboard = {
  kpis: {
    gold_set_accuracy_pct: number | null;
    iaa_krippendorff_alpha: number | null;
    rework_rate_pct: number | null;
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

export type ProjectRead = {
  id: string;
  name: string;
  org_id: string;
  vertical: string;
  status: string;
};

export type AgentQueryRead = {
  id: string;
  agent_name: string;
  project_id: string | null;
  query_text: string;
  answer_text: string;
  model_used: string | null;
  latency_ms: number | null;
  created_at: string;
  evidence_links: Array<{
    source_table: string;
    source_row_id: string;
    description: string;
  }>;
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

export type RiskAlertRead = {
  id: string;
  project_id: string;
  title: string;
  detail: string;
  alert_type: string;
  risk_tier: string;
  status: string;
  source_table: string | null;
  source_row_id: string | null;
  created_at: string;
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
