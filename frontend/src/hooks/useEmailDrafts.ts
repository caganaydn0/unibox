"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EmailDraft } from "@/types";

export function useEmailDrafts(statusFilter?: string) {
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listDrafts(statusFilter);
      setDrafts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Hata");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { drafts, loading, error, refresh };
}
