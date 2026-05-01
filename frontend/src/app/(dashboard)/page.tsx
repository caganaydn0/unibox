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
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-primary-900">Genel Bakış</h1>
        <p className="text-slate-500 mt-1 text-sm">Sistem durumu ve son aktiviteler</p>
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Intent Dağılımı */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-primary-900 mb-4">
            Intent Dağılımı (Son 7 Gün)
          </h2>
          {stats?.intents_breakdown?.length ? (
            <ul className="space-y-2">
              {stats.intents_breakdown.map((item) => (
                <li key={item.intent_type} className="flex items-center gap-3">
                  <span className="text-sm text-gray-600 w-48">
                    {INTENT_LABELS[item.intent_type] ?? item.intent_type}
                  </span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div
                      className="bg-primary-500 h-2 rounded-full"
                      style={{
                        width: `${Math.min(
                          100,
                          (item.count /
                            Math.max(...stats.intents_breakdown.map((i) => i.count))) *
                            100
                        )}%`,
                      }}
                    />
                  </div>
                  <span className="text-sm font-medium text-gray-700 w-6 text-right">
                    {item.count}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-400">Henüz veri yok.</p>
          )}
        </div>

        {/* Son Aktivite */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-primary-900 mb-4">Son Aktivite</h2>
          {activities.length ? (
            <ul className="space-y-3">
              {activities.slice(0, 8).map((a, i) => (
                <li key={i} className="flex items-start gap-3">
                  <div className="w-1.5 h-1.5 mt-2 rounded-full bg-primary-400 flex-shrink-0" />
                  <div>
                    <p className="text-sm text-gray-800">
                      {INTENT_LABELS[a.intent_type] ?? a.intent_type}
                      {a.requires_email && (
                        <span className="ml-1 text-xs text-orange-600">(e-posta gerekli)</span>
                      )}
                    </p>
                    <p className="text-xs text-gray-400">
                      {formatDistanceToNow(new Date(a.ts), { addSuffix: true, locale: tr })}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-400">Henüz aktivite yok.</p>
          )}
        </div>
      </div>
    </div>
  );
}
