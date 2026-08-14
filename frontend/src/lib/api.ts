/**
 * Typed API istemcisi — FastAPI backend'e fetch çağrıları.
 * BFF pattern: çağrılar Next.js üzerinden proxy'lenir (/api/backend/...).
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3000/api/backend";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("unibox_token");
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("unibox_refresh_token");
}

let isRefreshing = false;
let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  const rt = getRefreshToken();
  if (!rt) return false;

  try {
    const res = await fetch(`${BASE}/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("unibox_token", data.access_token);
    localStorage.setItem("unibox_refresh_token", data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  _isRetry = false
): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  if (res.status === 401 && !_isRetry && typeof window !== "undefined") {
    // Token expired — try refresh
    if (!isRefreshing) {
      isRefreshing = true;
      refreshPromise = tryRefreshToken().finally(() => {
        isRefreshing = false;
        refreshPromise = null;
      });
    }
    const ok = await (refreshPromise ?? tryRefreshToken());
    if (ok) {
      return request<T>(path, options, true);
    }
    // Refresh failed — redirect to login
    localStorage.removeItem("unibox_token");
    localStorage.removeItem("unibox_refresh_token");
    window.location.href = "/login";
    throw new Error("Oturum süresi doldu, giriş sayfasına yönlendiriliyorsunuz.");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  // Dashboard
  getStats: () => request<import("@/types").DashboardStats>("/v1/dashboard/stats"),
  getActivity: (limit = 50) =>
    request<{ activities: import("@/types").ActivityEvent[] }>(
      `/v1/dashboard/activity?limit=${limit}`
    ),

  // Email Drafts + IncomingReply (unified)
  listUnified: (status?: string, limit = 50) =>
    request<import("@/types").UnifiedEmailItem[]>(
      `/v1/emails/unified?limit=${limit}${status ? `&status=${status}` : ""}`
    ),

  // Email Drafts
  listDrafts: (status?: string, limit = 50) =>
    request<import("@/types").EmailDraft[]>(
      `/v1/emails/drafts?limit=${limit}${status ? `&status=${status}` : ""}`
    ),
  getDraft: (id: string) =>
    request<import("@/types").EmailDraft>(`/v1/emails/drafts/${id}`),
  updateDraft: (
    id: string,
    data: Partial<{
      subject: string;
      body: string;
      recipient_email: string;
      admin_notes: string;
    }>
  ) =>
    request<import("@/types").EmailDraft>(`/v1/emails/drafts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  approveDraft: (id: string) =>
    request<{ detail: string }>(`/v1/emails/drafts/${id}/approve`, {
      method: "POST",
    }),
  rejectDraft: (id: string, reason: string) =>
    request<{ detail: string }>(`/v1/emails/drafts/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  retryDraft: (id: string) =>
    request<{ detail: string }>(`/v1/emails/drafts/${id}/retry`, {
      method: "POST",
    }),

  // Knowledge Base
  listDocuments: (status?: string) =>
    request<import("@/types").KnowledgeDocument[]>(
      `/v1/knowledge/documents${status ? `?status=${status}` : ""}`
    ),
  deleteDocument: (id: string) =>
    request<{ detail: string }>(`/v1/knowledge/documents/${id}`, {
      method: "DELETE",
    }),
  reindexDocument: (id: string) =>
    request<{ detail: string }>(`/v1/knowledge/documents/${id}/reindex`, {
      method: "POST",
    }),
  uploadDocument: (formData: FormData) => {
    const token = getToken();
    return fetch(`${BASE}/v1/knowledge/documents`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    }).then((r) => r.json());
  },

  // Incoming Emails
  listIncoming: (status?: string, limit = 50) =>
    request<import("@/types").IncomingEmail[]>(
      `/v1/incoming/?limit=${limit}${status ? `&status=${status}` : ""}`
    ),
  getIncoming: (id: string) =>
    request<import("@/types").IncomingEmail>(`/v1/incoming/${id}`),
  updateIncoming: (
    id: string,
    data: Partial<{
      reply_subject: string;
      reply_body: string;
      admin_notes: string;
    }>
  ) =>
    request<import("@/types").IncomingEmail>(`/v1/incoming/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  approveIncoming: (id: string) =>
    request<{ detail: string }>(`/v1/incoming/${id}/approve`, {
      method: "POST",
    }),
  skipIncoming: (id: string, reason?: string) =>
    request<{ detail: string }>(`/v1/incoming/${id}/skip`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  retryIncoming: (id: string) =>
    request<{ detail: string }>(`/v1/incoming/${id}/retry`, {
      method: "POST",
    }),
  reanalyzeIncoming: (id: string) =>
    request<{ detail: string }>(`/v1/incoming/${id}/reanalyze`, {
      method: "POST",
    }),

  // Logs
  listLogs: (limit = 100) =>
    request<import("@/types").EmailLog[]>(`/v1/logs/emails?limit=${limit}`),

  // System Mode (Pilot / Co-Pilot)
  getSystemMode: () =>
    request<import("@/types").SystemModeConfig>("/v1/settings/system-mode"),
  setSystemMode: (mode: import("@/types").SystemMode) =>
    request<import("@/types").SystemModeConfig>("/v1/settings/system-mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    }),
};
