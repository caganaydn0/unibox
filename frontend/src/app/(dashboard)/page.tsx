"use client";

import { LayoutDashboard, Mail, Send, BookOpen } from "lucide-react";
import { StatsCard } from "@/components/dashboard/StatsCard";
import { useDashboardStats } from "@/hooks/useDashboardStats";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ActivityEvent } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";

const INTENT_LABELS: Record<string, string> = {
  transcript_request: "Transkript Talebi",
  certificate_request: "Sertifika Talebi",
  enrollment_letter: "Kayıt Belgesi",
  general_question: "Genel Soru",
  complaint: "Şikayet",
  grade_objection: "Not İtirazı",
  leave_of_absence: "İzin Talebi",
};

export default function OverviewPage() {
  const { stats, loading } = useDashboardStats();
  const [activities, setActivities] = useState<ActivityEvent[]>([]);

  useEffect(() => {
    api.getActivity(20).then((res) => setActivities(res.activities)).catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
      </div>
    );
  }

  return (
    <div>
      {/* Başlık */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-primary-950 tracking-tight">Genel Bakış</h1>
        <p className="text-slate-400 mt-1 text-sm">Sistem durumu ve son aktiviteler</p>
      </div>

      {/* İstatistik Kartları */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatsCard
          label="Aktif Oturum"
          value={stats?.active_sessions ?? 0}
          icon={LayoutDashboard}
        />
        <StatsCard
          label="Bekleyen E-posta"
          value={stats?.pending_emails ?? 0}
          icon={Mail}
          highlight={(stats?.pending_emails ?? 0) > 0}
        />
        <StatsCard
          label="Bugün Gönderim"
          value={stats?.sent_today ?? 0}
          icon={Send}
        />
        <StatsCard
          label="İndeksli Belge"
          value={stats?.total_documents ?? 0}
          icon={BookOpen}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Intent Dağılımı */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
          <h2 className="text-sm font-bold text-slate-700 mb-5 uppercase tracking-wide">
            Intent Dağılımı
            <span className="ml-2 text-[10px] font-semibold text-slate-400 normal-case tracking-normal">Son 7 Gün</span>
          </h2>
          {stats?.intents_breakdown?.length ? (
            <ul className="space-y-3">
              {stats.intents_breakdown.map((item) => {
                const max = Math.max(...stats.intents_breakdown.map((i) => i.count));
                const pct = Math.min(100, (item.count / max) * 100);
                return (
                  <li key={item.intent_type} className="flex items-center gap-3">
                    <span className="text-xs text-slate-500 w-40 shrink-0 truncate">
                      {INTENT_LABELS[item.intent_type] ?? item.intent_type}
                    </span>
                    <div className="flex-1 bg-slate-100 rounded-full h-1.5">
                      <div
                        className="bg-primary-500 h-1.5 rounded-full transition-all duration-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-slate-600 w-5 text-right tabular-nums">
                      {item.count}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">Henüz veri yok.</p>
          )}
        </div>

        {/* Son Aktivite */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
          <h2 className="text-sm font-bold text-slate-700 mb-5 uppercase tracking-wide">
            Son Aktivite
          </h2>
          {activities.length ? (
            <ul className="space-y-3">
              {activities.slice(0, 8).map((a, i) => (
                <li key={i} className="flex items-start gap-3">
                  <div className="w-1.5 h-1.5 mt-1.5 rounded-full bg-primary-400 flex-shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-slate-700 leading-snug">
                      {INTENT_LABELS[a.intent_type] ?? a.intent_type}
                      {a.requires_email && (
                        <span className="ml-1.5 inline-flex items-center rounded-md bg-orange-50 px-1.5 py-0.5 text-[10px] font-semibold text-orange-600 ring-1 ring-inset ring-orange-200">
                          e-posta
                        </span>
                      )}
                    </p>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      {formatDistanceToNow(new Date(a.ts), { addSuffix: true, locale: tr })}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">Henüz aktivite yok.</p>
          )}
        </div>
      </div>
    </div>
  );
}
