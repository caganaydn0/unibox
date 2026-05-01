"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DashboardStats } from "@/types";

export function useDashboardStats(refreshInterval = 30000) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getStats();
      setStats(data);
    } catch {
      // Sessizce başarısız — mevcut verileri koru
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, refreshInterval);
    return () => clearInterval(timer);
  }, [refresh, refreshInterval]);

  return { stats, loading, refresh };
}
