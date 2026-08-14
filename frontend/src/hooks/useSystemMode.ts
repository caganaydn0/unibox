"use client";

import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { useWsContext } from "@/contexts/WsContext";
import type { SystemMode } from "@/types";

export function useSystemMode() {
  const { systemMode, refreshSystemMode } = useWsContext();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setMode = useCallback(
    async (mode: SystemMode) => {
      setSaving(true);
      setError(null);
      try {
        await api.setSystemMode(mode);
        refreshSystemMode();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Hata");
        throw e;
      } finally {
        setSaving(false);
      }
    },
    [refreshSystemMode]
  );

  return { mode: systemMode, saving, error, setMode };
}
