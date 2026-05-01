"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { WsEvent } from "@/types";
import { useWebSocket } from "@/hooks/useWebSocket";
import { api } from "@/lib/api";

interface WsContextValue {
  subscribe: (handler: (event: WsEvent) => void) => () => void;
  pendingIncomingCount: number;
  pendingDraftCount: number;
}

const WsContext = createContext<WsContextValue | null>(null);

export function WsProvider({ children }: { children: React.ReactNode }) {
  const handlers = useRef<Set<(e: WsEvent) => void>>(new Set());
  const [pendingIncomingCount, setPendingIncomingCount] = useState(0);
  const [pendingDraftCount, setPendingDraftCount] = useState(0);
  const [wsUrl, setWsUrl] = useState("");

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

  useEffect(() => {
    const token = localStorage.getItem("unibox_token");
    if (token) {
      const base =
        (process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000") +
        "/api/v1/monitor/ws";
      setWsUrl(`${base}?token=${token}`);
    }
    refreshPendingCount();
    refreshDraftCount();
  }, [refreshPendingCount, refreshDraftCount]);

  const handleWsEvent = useCallback(
    (event: WsEvent) => {
      if (
        event.type === "incoming_email_received" ||
        event.type === "incoming_reply_ready" ||
        event.type === "incoming_reply_sent" ||
        event.type === "incoming_analysis_failed"
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
      handlers.current.forEach((h) => h(event));
    },
    [refreshPendingCount, refreshDraftCount]
  );

  useWebSocket(wsUrl, { onMessage: handleWsEvent, enabled: !!wsUrl });

  const subscribe = useCallback((handler: (event: WsEvent) => void) => {
    handlers.current.add(handler);
    return () => {
      handlers.current.delete(handler);
    };
  }, []);

  return (
    <WsContext.Provider value={{ subscribe, pendingIncomingCount, pendingDraftCount }}>
      {children}
    </WsContext.Provider>
  );
}

export function useWsContext() {
  const ctx = useContext(WsContext);
  if (!ctx) throw new Error("useWsContext must be used within WsProvider");
  return ctx;
}
