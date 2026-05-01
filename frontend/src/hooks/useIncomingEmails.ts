"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { IncomingEmail } from "@/types";

export function useIncomingEmails(statusFilter?: string) {
  const [emails, setEmails] = useState<IncomingEmail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listIncoming(statusFilter);
      setEmails(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Hata");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { emails, loading, error, refresh };
}
