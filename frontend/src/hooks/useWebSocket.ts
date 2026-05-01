"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WsEvent } from "@/types";

interface UseWebSocketOptions {
  onMessage: (event: WsEvent) => void;
  enabled?: boolean;
}

/**
 * Yeniden bağlanma özellikli WebSocket hook.
 * - Üstel geri çekilme: 1s → 2s → 4s → ... → 30s
 * - React StrictMode çift çağrısına karşı korumalı
 */
export function useWebSocket(url: string, options: UseWebSocketOptions) {
  const { onMessage, enabled = true } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const retryDelay = useRef(1000);
  const mountedRef = useRef(true);
  const [readyState, setReadyState] = useState<number>(WebSocket.CONNECTING);

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        retryDelay.current = 1000;
        setReadyState(WebSocket.OPEN);
      };

      ws.onmessage = (e) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(e.data) as WsEvent;
          if (data.type === "ping") {
            ws.send(JSON.stringify({ type: "pong" }));
            return;
          }
          onMessage(data);
        } catch {
          // Parse hatası yoksay
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setReadyState(WebSocket.CLOSED);
        // Üstel geri çekilme ile yeniden bağlan
        const delay = retryDelay.current;
        retryDelay.current = Math.min(delay * 2, 30000);
        setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };

    } catch {
      // Bağlantı hatası — yeniden dene
      setTimeout(connect, retryDelay.current);
    }
  }, [url, enabled, onMessage]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) connect();

    return () => {
      mountedRef.current = false;
      wsRef.current?.close();
    };
  }, [connect, enabled]);

  const send = useCallback((data: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { readyState, send };
}
