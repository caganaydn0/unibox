"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Send, Trash2, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { chatApi, type ChatFrame } from "@/lib/chatApi";
import type { ChatMessage, WsEvent } from "@/types";
import { MessageBubble } from "@/components/chat/MessageBubble";

// chat.py:45 MAX_MESSAGE_LEN ile aynı — sunucu zaten reddediyor, burada
// öğrenciye erkenden geri bildirim vermek için.
const MAX_MESSAGE_LEN = 4000;

const TOKEN_KEY = "unibox_chat_token";
const EXPIRES_KEY = "unibox_chat_expires_days";

type BootstrapStatus = "loading" | "ready" | "error";

export default function ChatPage() {
  const [bootstrapStatus, setBootstrapStatus] = useState<BootstrapStatus>("loading");
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [expiresInDays, setExpiresInDays] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [latestState, setLatestState] = useState("IDLE");
  const [wsEnabled, setWsEnabled] = useState(true);
  const [deleted, setDeleted] = useState(false);

  const recoveringRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const bootstrap = useCallback(async () => {
    setBootstrapStatus("loading");
    const existingToken = sessionStorage.getItem(TOKEN_KEY);
    if (existingToken) {
      setSessionToken(existingToken);
      const savedExpires = sessionStorage.getItem(EXPIRES_KEY);
      setExpiresInDays(savedExpires ? Number(savedExpires) : null);
      setBootstrapStatus("ready");
      return;
    }
    try {
      const res = await chatApi.startSession();
      sessionStorage.setItem(TOKEN_KEY, res.session_token);
      sessionStorage.setItem(EXPIRES_KEY, String(res.expires_in_days));
      setSessionToken(res.session_token);
      setExpiresInDays(res.expires_in_days);
      setBootstrapStatus("ready");
    } catch {
      setBootstrapStatus("error");
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  // Sayfa yenilenmiş olabilir — mevcut jetonla geçmişi yükle.
  useEffect(() => {
    if (bootstrapStatus !== "ready" || !sessionToken) return;
    chatApi
      .getHistory(sessionToken)
      .then((res) => {
        if (res.messages.length) {
          setMessages(res.messages.map((m) => ({ role: m.role, content: m.content, ts: m.ts })));
        }
      })
      .catch(() => {
        // Geçmiş yüklenemedi (yeni oturum olabilir) — sessizce boş başla.
        // Jeton gerçekten geçersizse WS bağlantısı 4401 ile bunu bildirecek.
      });
  }, [sessionToken, bootstrapStatus]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const applyFrame = useCallback((frame: ChatFrame) => {
    if (frame.type === "message") {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: frame.content ?? "",
          draftPreview: frame.draft_preview,
        },
      ]);
      setLatestState(frame.state ?? "IDLE");
      setSending(false);
    } else if (frame.type === "error") {
      setMessages((prev) => [
        ...prev,
        { role: "system", content: frame.message ?? "Bir hata oluştu." },
      ]);
      setSending(false);
    } else if (frame.type === "draft_rejected") {
      setMessages((prev) => [
        ...prev,
        {
          role: "system",
          content: `Taslağınız reddedildi${frame.reason ? `: ${frame.reason}` : "."}`,
        },
      ]);
      setLatestState("IDLE");
    } else if (frame.type === "email_sent") {
      setMessages((prev) => [
        ...prev,
        { role: "system", content: frame.message ?? "E-postanız iletildi." },
      ]);
      setLatestState("IDLE");
    }
  }, []);

  const handleInvalidSession = useCallback(() => {
    if (recoveringRef.current) return;
    recoveringRef.current = true;
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(EXPIRES_KEY);
    setWsEnabled(false);
    setLatestState("IDLE");
    setMessages((prev) => [
      ...prev,
      { role: "system", content: "Önceki oturumun süresi doldu, yeni bir sohbet başlatıldı." },
    ]);
    bootstrap().finally(() => {
      recoveringRef.current = false;
      setWsEnabled(true);
    });
  }, [bootstrap]);

  const wsUrl = useMemo(() => {
    if (!sessionToken) return "";
    const base = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
    return `${base}/api/v1/chat/ws/${sessionToken}`;
  }, [sessionToken]);

  const onWsMessage = useCallback(
    (event: WsEvent) => {
      applyFrame(event as unknown as ChatFrame);
    },
    [applyFrame]
  );

  const onWsClose = useCallback(
    (event: CloseEvent) => {
      if (event.code === 4401) {
        handleInvalidSession();
      }
    },
    [handleInvalidSession]
  );

  const { readyState, send } = useWebSocket(wsUrl, {
    onMessage: onWsMessage,
    onClose: onWsClose,
    enabled: bootstrapStatus === "ready" && !!sessionToken && wsEnabled && !deleted,
  });

  const sendText = useCallback(
    async (raw: string) => {
      const content = raw.trim();
      if (!content || content.length > MAX_MESSAGE_LEN || !sessionToken || sending) return;

      setMessages((prev) => [...prev, { role: "user", content, ts: new Date().toISOString() }]);
      setInput("");
      setSending(true);

      if (readyState === WebSocket.OPEN) {
        send({ type: "message", content });
        return;
      }

      try {
        const frame = await chatApi.sendMessage(sessionToken, content);
        applyFrame(frame);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            role: "system",
            content: err instanceof Error ? err.message : "Mesaj gönderilemedi.",
          },
        ]);
        setSending(false);
      }
    },
    [sessionToken, sending, readyState, send, applyFrame]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendText(input);
  };

  const handleDeleteSession = async () => {
    if (!sessionToken) return;
    if (!confirm("Sohbetinizi silmek istediğinize emin misiniz? Bu işlem geri alınamaz.")) return;
    try {
      await chatApi.deleteSession(sessionToken);
    } catch {
      // Sunucu hatası olsa bile yerel durumu temizlemeye devam et.
    }
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(EXPIRES_KEY);
    setWsEnabled(false);
    setDeleted(true);
  };

  const handleRestartAfterDelete = () => {
    setDeleted(false);
    setMessages([]);
    setLatestState("IDLE");
    setSessionToken(null);
    setWsEnabled(true);
    bootstrap();
  };

  const lastDraftIndex = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].draftPreview) return i;
    }
    return -1;
  }, [messages]);

  const draftActionsDisabled = sending || latestState !== "DRAFT_CREATED";

  // --- Tam sayfa durumları ---

  if (bootstrapStatus === "error") {
    return (
      <CenteredCard>
        <p className="text-sm text-gray-700 mb-4">
          Sunucuya bağlanılamıyor. Lütfen internet bağlantınızı kontrol edip tekrar deneyin.
        </p>
        <button
          onClick={bootstrap}
          className="flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-all mx-auto"
        >
          <RefreshCw className="w-4 h-4" />
          Tekrar dene
        </button>
      </CenteredCard>
    );
  }

  if (deleted) {
    return (
      <CenteredCard>
        <p className="text-sm text-gray-700 mb-4">
          Sohbetiniz silindi. Kurumsal e-posta kayıtları (varsa) saklanmaya devam eder.
        </p>
        <button
          onClick={handleRestartAfterDelete}
          className="flex items-center gap-2 rounded-xl bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-all mx-auto"
        >
          <RefreshCw className="w-4 h-4" />
          Yeni sohbet başlat
        </button>
      </CenteredCard>
    );
  }

  const badge = connectionBadge(readyState, wsEnabled);

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col items-center">
      <div className="w-full max-w-2xl flex flex-col min-h-screen">
        {/* Header */}
        <header className="sticky top-0 z-10 bg-white border-b border-slate-200 px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-sm font-bold text-gray-900">UniBox Sohbet</h1>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className={`w-1.5 h-1.5 rounded-full ${badge.color}`} />
                <span className="text-[11px] text-slate-500">{badge.text}</span>
              </div>
            </div>
            <button
              onClick={handleDeleteSession}
              disabled={!sessionToken}
              title="Sohbetimi sil"
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-red-50 hover:text-red-600 disabled:opacity-40 transition-all"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Sohbetimi sil
            </button>
          </div>
          <div className="flex items-center gap-1.5 mt-2 text-[11px] text-slate-400">
            <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
            <span>
              Verileriniz KVKK kapsamında{expiresInDays ? ` ${expiresInDays} gün` : ""} saklanır.
            </span>
          </div>
        </header>

        {/* Mesajlar */}
        <div className="flex-1 px-4 py-4 overflow-y-auto">
          {messages.length === 0 && bootstrapStatus === "ready" && (
            <p className="text-sm text-slate-400 text-center mt-8">
              Merhaba! Üniversite süreçleri hakkında bir soru sorabilir ya da bir talep
              başlatabilirsiniz.
            </p>
          )}
          {messages.map((m, i) => (
            <MessageBubble
              key={i}
              message={m}
              onApproveDraft={i === lastDraftIndex ? () => sendText("Evet, gönder") : undefined}
              onCancelDraft={i === lastDraftIndex ? () => sendText("Hayır, iptal") : undefined}
              draftActionsDisabled={draftActionsDisabled}
            />
          ))}
          {sending && (
            <div className="flex justify-start mb-3">
              <div className="bg-white rounded-2xl rounded-bl-sm ring-1 ring-slate-200 px-4 py-2.5 shadow-sm">
                <Loader2 className="w-4 h-4 text-slate-400 animate-spin" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Giriş */}
        <form
          onSubmit={handleSubmit}
          className="sticky bottom-0 bg-white border-t border-slate-200 px-4 py-3"
        >
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendText(input);
                }
              }}
              placeholder="Mesajınızı yazın..."
              rows={1}
              disabled={bootstrapStatus !== "ready" || !sessionToken}
              className="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={
                !input.trim() ||
                input.length > MAX_MESSAGE_LEN ||
                sending ||
                bootstrapStatus !== "ready" ||
                !sessionToken
              }
              className="flex items-center justify-center rounded-xl bg-primary-600 w-10 h-10 shrink-0 text-white hover:bg-primary-700 disabled:opacity-40 transition-all"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
          {input.length > MAX_MESSAGE_LEN * 0.9 && (
            <p
              className={`text-[11px] mt-1 text-right ${
                input.length > MAX_MESSAGE_LEN ? "text-red-600" : "text-slate-400"
              }`}
            >
              {input.length} / {MAX_MESSAGE_LEN}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}

function CenteredCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-100 flex items-center justify-center p-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-xl p-8 text-center">
        {children}
      </div>
    </div>
  );
}

function connectionBadge(readyState: number, wsEnabled: boolean): { text: string; color: string } {
  if (!wsEnabled) return { text: "Oturum yenileniyor...", color: "bg-amber-400" };
  if (readyState === WebSocket.OPEN) return { text: "Bağlı", color: "bg-green-500" };
  if (readyState === WebSocket.CONNECTING) return { text: "Bağlanıyor...", color: "bg-amber-400" };
  return { text: "Bağlantı kesildi, yeniden deneniyor...", color: "bg-red-500" };
}
