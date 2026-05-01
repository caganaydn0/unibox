"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { WsEvent } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";

interface ConversationCard {
  conversation_id: string;
  session_prefix: string;
  intent_type: string;
  state: string | null;
  last_content: string;
  ts: string;
}

const WS_URL = `${(process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000")}/api/v1/monitor/ws`;

const INTENT_LABELS: Record<string, string> = {
  transcript_request: "Transkript",
  certificate_request: "Sertifika",
  general_question: "Genel Soru",
  complaint: "Şikayet",
};

export default function MonitoringPage() {
  const [conversations, setConversations] = useState<Map<string, ConversationCard>>(new Map());
  const [connected, setConnected] = useState(false);
  const token = typeof window !== "undefined" ? localStorage.getItem("unibox_token") : null;

  const handleMessage = useCallback((event: WsEvent) => {
    if (event.type === "message" || event.type === "intent_detected") {
      setConversations((prev) => {
        const next = new Map(prev);
        const id = event.conversation_id as string;
        const existing = next.get(id);
        next.set(id, {
          conversation_id: id,
          session_prefix: (event.session_token_prefix as string) ?? id.slice(0, 8),
          intent_type: (event.intent_type as string) ?? existing?.intent_type ?? "—",
          state: (event.state as string) ?? existing?.state ?? null,
          last_content: (event.content_preview as string) ?? existing?.last_content ?? "",
          ts: new Date().toISOString(),
        });
        return next;
      });
    }
    if (event.type === "draft_created" || event.type === "email_pending_approval") {
      const id = event.conversation_id as string;
      setConversations((prev) => {
        const next = new Map(prev);
        const existing = next.get(id);
        if (existing) {
          next.set(id, { ...existing, state: event.status as string ?? "PENDING_APPROVAL" });
        }
        return next;
      });
    }
  }, []);

  const { readyState } = useWebSocket(
    token ? `${WS_URL}?token=${token}` : "",
    { onMessage: handleMessage, enabled: !!token }
  );

  useEffect(() => {
    setConnected(readyState === WebSocket.OPEN);
  }, [readyState]);

  const cards = Array.from(conversations.values()).sort(
    (a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-primary-900">Canlı İzleme</h1>
          <p className="text-slate-500 mt-1 text-sm">Gerçek zamanlı öğrenci konuşmaları</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${connected ? "bg-green-400 animate-pulse" : "bg-slate-300"}`} />
          <span className="text-sm text-slate-500">
            {connected ? `${conversations.size} aktif oturum` : "Bağlanıyor..."}
          </span>
        </div>
      </div>

      {!token && (
        <div className="rounded-lg bg-yellow-50 border border-yellow-200 p-4 text-sm text-yellow-800">
          WebSocket bağlantısı için giriş yapmalısınız.
        </div>
      )}

      {cards.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          Henüz aktif oturum yok. Bot ile konuşmalar başladığında burada görünecek.
        </div>
      ) : (
        <div className="space-y-3">
          {cards.map((card) => (
            <div key={card.conversation_id} className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm hover:border-primary-200 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-xs bg-primary-50 px-2 py-0.5 rounded text-primary-700">
                      #{card.session_prefix}
                    </span>
                    <span className="text-xs text-gray-500">
                      {INTENT_LABELS[card.intent_type] ?? card.intent_type}
                    </span>
                    {card.state && (
                      <>
                        <span className="text-xs text-gray-300">•</span>
                        <span className="text-xs text-indigo-600">{card.state}</span>
                      </>
                    )}
                  </div>
                  {card.last_content && (
                    <p className="text-sm text-gray-700 truncate">
                      {card.last_content}
                    </p>
                  )}
                </div>
                <span className="text-xs text-gray-400 flex-shrink-0">
                  {formatDistanceToNow(new Date(card.ts), { addSuffix: true, locale: tr })}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
