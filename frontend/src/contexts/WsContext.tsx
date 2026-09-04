"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { SystemMode, WsEvent } from "@/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { api } from "@/lib/api";

interface WsContextValue {
  subscribe: (handler: (event: WsEvent) => void) => () => void;
  pendingIncomingCount: number;
  pendingDraftCount: number;
  systemMode: SystemMode | null;
  refreshSystemMode: () => void;
}

const WsContext = createContext<WsContextValue | null>(null);

export function WsProvider({ children }: { children: React.ReactNode }) {
  const handlers = useRef<Set<(e: WsEvent) => void>>(new Set());
  const [pendingIncomingCount, setPendingIncomingCount] = useState(0);
  const [pendingDraftCount, setPendingDraftCount] = useState(0);
  const [systemMode, setSystemMode] = useState<SystemMode | null>(null);
  const [wsUrl, setWsUrl] = useState("");
  const tokenRef = useRef<string | null>(null);

  const refreshPendingCount = useCallback(() => {
    api
      .listIncoming("PENDING_REVIEW", 200)
      .then((data) => setPendingIncomingCount(data.length))
      .catch(() => {});
  }, []);

  const refreshDraftCount = useCallback(() => {
    api
      .listDrafts("PENDING_APPROVAL", 200)
      .then((data) => setPendingDraftCount(data.length))
      .catch(() => {});
  }, []);

  const refreshSystemMode = useCallback(() => {
    api
      .getSystemMode()
      .then((data) => setSystemMode(data.mode))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("unibox_token");
    if (token) {
      // Jeton artık URL'de DEĞİL (uvicorn/proxy loglarına düz metin JWT
      // düşmesin diye) — bağlantı açılınca ilk çerçeve olarak gönderiliyor,
      // bkz. getInitialMessage aşağıda.
      tokenRef.current = token;
      const base =
        (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000") +
        "/api/v1/monitor/ws";
      setWsUrl(base);
    }
    refreshPendingCount();
    refreshDraftCount();
    refreshSystemMode();
  }, [refreshPendingCount, refreshDraftCount, refreshSystemMode]);

  const handleWsEvent = useCallback(
    (event: WsEvent) => {
      if (
        event.type === "incoming_email_received" ||
        event.type === "incoming_reply_ready" ||
        event.type === "incoming_reply_sent" ||
        event.type === "incoming_analysis_failed" ||
        event.type === "incoming_email_auto_replied"
      ) {
        refreshPendingCount();
      }
      if (
        event.type === "email_pending_approval" ||
        event.type === "email_approved" ||
        event.type === "email_rejected" ||
        event.type === "email_sent"
      ) {
        refreshDraftCount();
      }
      if (event.type === "system_mode_changed") {
        refreshSystemMode();
      }
      handlers.current.forEach((h) => h(event));
    },
    [refreshPendingCount, refreshDraftCount, refreshSystemMode]
  );

  useWebSocket(wsUrl, {
    onMessage: handleWsEvent,
    enabled: !!wsUrl,
    getInitialMessage: () =>
      tokenRef.current ? { type: "auth", token: tokenRef.current } : null,
  });

  const subscribe = useCallback((handler: (event: WsEvent) => void) => {
    handlers.current.add(handler);
    return () => {
      handlers.current.delete(handler);
    };
  }, []);

  return (
    <WsContext.Provider
      value={{
        subscribe,
        pendingIncomingCount,
        pendingDraftCount,
        systemMode,
        refreshSystemMode,
      }}
    >
      {children}
    </WsContext.Provider>
  );
}

export function useWsContext() {
  const ctx = useContext(WsContext);
  if (!ctx) throw new Error("useWsContext must be used within WsProvider");
  return ctx;
}
