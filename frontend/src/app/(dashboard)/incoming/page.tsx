"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw, CheckCircle, SkipForward, RotateCcw } from "lucide-react";
import { useIncomingEmails } from "@/hooks/useIncomingEmails";
import { api } from "@/lib/api";
import { useWsContext } from "@/contexts/WsContext";
import { format, formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";
import clsx from "clsx";
import type { IncomingEmailStatus } from "@/types";

const STATUS_CONFIG: Record<IncomingEmailStatus, { label: string; className: string }> = {
  RECEIVED: { label: "Alındı", className: "bg-blue-100 text-blue-700" },
  ANALYZING: { label: "Analiz Ediliyor", className: "bg-yellow-100 text-yellow-700" },
  REPLY_GENERATED: { label: "Yanıt Hazır", className: "bg-indigo-100 text-indigo-700" },
  PENDING_REVIEW: { label: "İnceleme Bekliyor", className: "bg-orange-100 text-orange-700" },
  APPROVED: { label: "Onaylandı", className: "bg-green-100 text-green-700" },
  REPLIED: { label: "Yanıtlandı", className: "bg-emerald-100 text-emerald-700" },
  FAILED: { label: "Hata", className: "bg-red-100 text-red-700" },
  SKIPPED: { label: "Atlandı", className: "bg-gray-100 text-gray-500" },
  ANALYSIS_FAILED: { label: "Analiz Hatası", className: "bg-red-100 text-red-600" },
};

const INTENT_LABELS: Record<string, string> = {
  transcript_request: "Transkript",
  certificate_request: "Sertifika",
  enrollment_letter: "Kayıt Belgesi",
  general_question: "Genel Soru",
  complaint: "Şikayet",
  grade_objection: "Not İtirazı",
  leave_of_absence: "İzin/Kayıt Dondurma",
};

export default function IncomingPage() {
  const [filter, setFilter] = useState("PENDING_REVIEW");
  const { emails, loading, error, refresh } = useIncomingEmails(filter || undefined);
  const [actionId, setActionId] = useState<string | null>(null);
  const { subscribe, systemMode } = useWsContext();

  useEffect(() => {
    return subscribe((event) => {
      if (
        event.type === "incoming_email_received" ||
        event.type === "incoming_reply_ready" ||
        event.type === "incoming_reply_sent" ||
        event.type === "incoming_analysis_failed"
      ) {
        refresh();
      }
    });
  }, [subscribe, refresh]);

  const handleApprove = async (id: string) => {
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

  const handleSkip = async (id: string) => {
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

  const handleRetry = async (id: string) => {
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

  const handleReanalyze = async (id: string) => {
    setActionId(id);
    try {
      await api.reanalyzeIncoming(id);
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
          <h1 className="text-2xl font-bold text-primary-900">Gelen E-postalar</h1>
          <p className="text-slate-500 mt-1 text-sm">
            Öğrenci e-postalarını inceleyin ve AI yanıtlarını onaylayın
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

      {systemMode === "PILOT" && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <span className="font-semibold">Pilot Modu aktif</span> — gelen e-postalara AI
          yanıtları otomatik olarak, incelemeye gerek kalmadan gönderiliyor.
        </div>
      )}

      {/* Filtreler */}
      <div className="flex gap-2 mb-4 flex-wrap">
        {[
          { value: "", label: "Tümü" },
          { value: "PENDING_REVIEW", label: "İnceleme Bekliyor" },
          { value: "REPLIED", label: "Yanıtlandı" },
          { value: "ANALYZING", label: "Analiz Ediliyor" },
          { value: "FAILED", label: "Hata" },
          { value: "SKIPPED", label: "Atlandı" },
          { value: "ANALYSIS_FAILED", label: "Analiz Hatası" },
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
      ) : error ? (
        <div className="text-center py-16">
          <p className="text-red-500 mb-2">Hata: {error}</p>
          <button onClick={refresh} className="text-sm text-primary-600 hover:underline">Tekrar Dene</button>
        </div>
      ) : emails.length === 0 ? (
        <div className="text-center py-16 text-gray-400">Gelen e-posta bulunamadı.</div>
      ) : (
        <div className="space-y-3">
          {emails.map((email) => {
            const statusCfg = STATUS_CONFIG[email.status] ?? STATUS_CONFIG.RECEIVED;
            return (
              <div
                key={email.id}
                className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm hover:border-primary-200 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={clsx(
                          "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
                          statusCfg.className
                        )}
                      >
                        {statusCfg.label}
                      </span>
                      {email.auto_approved && (
                        <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">
                          Otomatik (Pilot)
                        </span>
                      )}
                      {email.intent_type && (
                        <>
                          <span className="text-xs text-gray-400">
                            {INTENT_LABELS[email.intent_type] ?? email.intent_type}
                          </span>
                          <span className="text-xs text-gray-300">•</span>
                        </>
                      )}
                      <span
                        className="text-xs text-gray-400"
                        title={formatDistanceToNow(new Date(email.received_at), {
                          addSuffix: true,
                          locale: tr,
                        })}
                      >
                        {format(new Date(email.received_at), "d MMM HH:mm", {
                          locale: tr,
                        })}
                      </span>
                      {email.has_attachments && (
                        <span className="text-xs text-gray-400">📎</span>
                      )}
                    </div>
                    <p className="font-medium text-gray-900 truncate">
                      {email.subject || "(konu yok)"}
                    </p>
                    <p className="text-sm text-gray-500 truncate">
                      {email.sender_name || `#${email.sender_email_hash.slice(0, 8)}`}
                    </p>
                    {email.reply_subject && (
                      <p className="text-xs text-primary-600 mt-1 truncate">
                        AI Yanıt: {email.reply_subject}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Link
                      href={`/incoming/${email.id}`}
                      className="text-xs text-primary-600 hover:underline"
                    >
                      Detay
                    </Link>
                    {email.status === "PENDING_REVIEW" && (
                      <>
                        <button
                          onClick={() => handleApprove(email.id)}
                          disabled={actionId === email.id}
                          className="flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                        >
                          <CheckCircle className="w-3.5 h-3.5" />
                          Onayla
                        </button>
                        <button
                          onClick={() => handleSkip(email.id)}
                          disabled={actionId === email.id}
                          className="flex items-center gap-1 rounded-lg bg-gray-50 border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                        >
                          <SkipForward className="w-3.5 h-3.5" />
                          Atla
                        </button>
                      </>
                    )}
                    {email.status === "FAILED" && (
                      <button
                        onClick={() => handleRetry(email.id)}
                        disabled={actionId === email.id}
                        className="flex items-center gap-1 rounded-lg bg-orange-50 border border-orange-200 px-3 py-1.5 text-xs font-medium text-orange-700 hover:bg-orange-100 disabled:opacity-50"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        Tekrar
                      </button>
                    )}
                    {email.status === "ANALYSIS_FAILED" && (
                      <button
                        onClick={() => handleReanalyze(email.id)}
                        disabled={actionId === email.id}
                        className="flex items-center gap-1 rounded-lg bg-blue-50 border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        Yeniden Analiz
                      </button>
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
