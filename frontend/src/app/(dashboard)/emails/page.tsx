"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw, CheckCircle, XCircle, SkipForward, Mail, Inbox, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";
import type { UnifiedEmailItem } from "@/types";

const INTENT_LABELS: Record<string, string> = {
  transcript_request: "Transkript",
  certificate_request: "Sertifika",
  enrollment_letter: "Kayıt Belgesi",
  general_question: "Genel Soru",
  complaint: "Şikayet",
  grade_objection: "Not İtirazı",
  leave_of_absence: "İzin/Kayıt Dondurma",
};

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  PENDING_APPROVAL: { label: "Onay Bekliyor", className: "bg-orange-100 text-orange-700" },
  APPROVED:         { label: "Onaylandı",     className: "bg-green-100 text-green-700" },
  SENT:             { label: "Gönderildi",    className: "bg-emerald-100 text-emerald-700" },
  REJECTED:         { label: "Reddedildi",    className: "bg-red-100 text-red-700" },
  FAILED:           { label: "Hata",          className: "bg-red-100 text-red-700" },
};

export default function EmailsPage() {
  const [filter, setFilter] = useState("PENDING_APPROVAL");
  const [items, setItems] = useState<UnifiedEmailItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listUnified(filter || undefined);
      setItems(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleApproveDraft = async (id: string) => {
    setActionId(id);
    try {
      await api.approveDraft(id);
      await refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setActionId(null);
    }
  };

  const handleRejectDraft = async (id: string) => {
    const reason = window.prompt("Red nedeni:");
    if (!reason) return;
    setActionId(id);
    try {
      await api.rejectDraft(id, reason);
      await refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setActionId(null);
    }
  };

  const handleApproveIncoming = async (id: string) => {
    setActionId(id);
    try {
      await api.approveIncoming(id);
      await refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setActionId(null);
    }
  };

  const handleRetryDraft = async (id: string) => {
    setActionId(id);
    try {
      await api.retryDraft(id);
      await refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setActionId(null);
    }
  };

  const handleRetryIncoming = async (id: string) => {
    setActionId(id);
    try {
      await api.retryIncoming(id);
      await refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setActionId(null);
    }
  };

  const handleSkipIncoming = async (id: string) => {
    const reason = window.prompt("Atlama nedeni (opsiyonel):");
    setActionId(id);
    try {
      await api.skipIncoming(id, reason || undefined);
      await refresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setActionId(null);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-primary-900">E-posta Onayları</h1>
          <p className="text-slate-500 mt-1 text-sm">
            Giden taslaklar ve gelen e-posta yanıtlarını yönetin
          </p>
        </div>
        <button
          onClick={refresh}
          className="flex items-center gap-2 text-sm text-slate-500 hover:text-primary-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Yenile
        </button>
      </div>

      {/* Filtreler */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {[
          { value: "",                 label: "Tümü" },
          { value: "PENDING_APPROVAL", label: "Onay Bekliyor" },
          { value: "APPROVED",         label: "Onaylandı" },
          { value: "SENT",             label: "Gönderildi" },
          { value: "REJECTED",         label: "Reddedildi" },
          { value: "FAILED",           label: "Hata" },
        ].map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setFilter(value)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === value
                ? "bg-primary-600 text-white shadow-sm"
                : "bg-white border border-slate-200 text-slate-600 hover:border-primary-300 hover:text-primary-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-400">Kayıt bulunamadı.</div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const statusCfg = STATUS_LABELS[item.status] ?? STATUS_LABELS.PENDING_APPROVAL;
            const isDraft = item.item_type === "draft";
            const detailHref = isDraft ? `/emails/${item.id}` : `/incoming/${item.id}`;

            return (
              <div
                key={`${item.item_type}-${item.id}`}
                className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm hover:border-primary-200 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {/* Tür rozeti */}
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                          isDraft
                            ? "bg-blue-50 text-blue-600"
                            : "bg-purple-50 text-purple-600"
                        }`}
                      >
                        {isDraft ? <Mail className="w-3 h-3" /> : <Inbox className="w-3 h-3" />}
                        {isDraft ? "Taslak" : "Gelen Yanıt"}
                      </span>

                      {/* Durum */}
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusCfg.className}`}
                      >
                        {statusCfg.label}
                      </span>

                      {item.intent_type && (
                        <span className="text-xs text-gray-400">
                          {INTENT_LABELS[item.intent_type] ?? item.intent_type}
                        </span>
                      )}
                      <span className="text-xs text-gray-300">•</span>
                      <span className="text-xs text-gray-400">
                        {formatDistanceToNow(new Date(item.created_at), {
                          addSuffix: true,
                          locale: tr,
                        })}
                      </span>
                    </div>

                    <p className="font-medium text-gray-900 truncate">
                      {item.subject || "(konu yok)"}
                    </p>

                    {isDraft ? (
                      <p className="text-sm text-gray-500 truncate">
                        Kime: {item.recipient_display || "—"}
                      </p>
                    ) : (
                      <p className="text-sm text-gray-500 truncate">
                        Gönderen: {item.sender_display || "—"}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Link
                      href={detailHref}
                      className="text-xs text-primary-600 hover:underline"
                    >
                      Detay
                    </Link>

                    {/* Draft onay/red */}
                    {isDraft && item.status === "PENDING_APPROVAL" && (
                      <>
                        <button
                          onClick={() => handleApproveDraft(item.id)}
                          disabled={actionId === item.id}
                          className="flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                        >
                          <CheckCircle className="w-3.5 h-3.5" />
                          Onayla
                        </button>
                        <button
                          onClick={() => handleRejectDraft(item.id)}
                          disabled={actionId === item.id}
                          className="flex items-center gap-1 rounded-lg bg-red-50 border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"
                        >
                          <XCircle className="w-3.5 h-3.5" />
                          Reddet
                        </button>
                      </>
                    )}

                    {/* Draft retry */}
                    {isDraft && item.status === "FAILED" && (
                      <button
                        onClick={() => handleRetryDraft(item.id)}
                        disabled={actionId === item.id}
                        className="flex items-center gap-1 rounded-lg bg-orange-50 border border-orange-200 px-3 py-1.5 text-xs font-medium text-orange-700 hover:bg-orange-100 disabled:opacity-50"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        Tekrar
                      </button>
                    )}

                    {/* Incoming reply retry */}
                    {!isDraft && item.status === "FAILED" && (
                      <button
                        onClick={() => handleRetryIncoming(item.id)}
                        disabled={actionId === item.id}
                        className="flex items-center gap-1 rounded-lg bg-orange-50 border border-orange-200 px-3 py-1.5 text-xs font-medium text-orange-700 hover:bg-orange-100 disabled:opacity-50"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        Tekrar
                      </button>
                    )}

                    {/* Incoming reply onay/atla */}
                    {!isDraft && item.status === "PENDING_APPROVAL" && (
                      <>
                        <button
                          onClick={() => handleApproveIncoming(item.id)}
                          disabled={actionId === item.id}
                          className="flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                        >
                          <CheckCircle className="w-3.5 h-3.5" />
                          Onayla & Gönder
                        </button>
                        <button
                          onClick={() => handleSkipIncoming(item.id)}
                          disabled={actionId === item.id}
                          className="flex items-center gap-1 rounded-lg bg-gray-50 border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                        >
                          <SkipForward className="w-3.5 h-3.5" />
                          Atla
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
