import type { AppRole, AuthSession, MeUser, OrganisationRead, UserRead } from "@/types/auth";
import type { KnowledgeAskResponseApi, KnowledgeDocumentApi } from "@/types/knowledge";

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
    throw new ApiError(response.status, err?.code ?? "API_ERROR", err?.message ?? "Request failed.");
  }
  return body as T;
}

async function parseApiError(response: Response): Promise<ApiError> {
  const body = (await response.json().catch(() => ({}))) as ErrorBody;
  const err = body?.error;
  return new ApiError(response.status, err?.code ?? "API_ERROR", err?.message ?? "Request failed.");
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
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

export async function listKnowledgeDocuments(): Promise<KnowledgeDocumentApi[]> {
  const body = await apiFetch<{ data: KnowledgeDocumentApi[] }>("/knowledge/documents");
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

export async function askKnowledgeAgent(queryText: string): Promise<KnowledgeAskResponseApi> {
  const body = await apiFetch<{ data: KnowledgeAskResponseApi }>("/knowledge/ask", {
    method: "POST",
    body: JSON.stringify({ query_text: queryText }),
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
