/**
 * Öğrenci sohbet istemcisi — lib/api.ts'den KASITLI olarak ayrı.
 *
 * api.ts'deki paylaşılan request() her çağrıya admin JWT'sini ekliyor ve
 * 401'de /login'e yönlendiriyor. Sohbet uçları kimlik doğrulaması istemiyor
 * ve bir öğrenci hiçbir zaman admin login ekranına fırlatılmamalı — bu yüzden
 * burada auth header'ı ve yönlendirme mantığı olmayan düz fetch sarmalayıcıları
 * kullanılıyor.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3000/api/backend";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface ChatFrame {
  type: "message" | "error" | "draft_rejected" | "email_sent" | string;
  content?: string;
  message?: string;
  reason?: string;
  state?: string;
  draft_id?: string | null;
  draft_preview?: { subject: string; body: string };
}

export interface ChatHistoryEntry {
  role: "user" | "assistant";
  content: string;
  ts: string;
}

export const chatApi = {
  startSession: () =>
    request<{ session_token: string; expires_in_days: number }>("/v1/chat/session", {
      method: "POST",
    }),

  getHistory: (token: string) =>
    request<{ messages: ChatHistoryEntry[] }>(`/v1/chat/history/${token}`),

  sendMessage: (token: string, content: string) =>
    request<ChatFrame>("/v1/chat/message", {
      method: "POST",
      body: JSON.stringify({ session_token: token, content }),
    }),

  deleteSession: (token: string) =>
    request<{ detail: string }>(`/v1/chat/session/${token}`, {
      method: "DELETE",
    }),
};
