"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle, SkipForward, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import type { IncomingEmail, IncomingEmailStatus } from "@/types";
import clsx from "clsx";

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
  transcript_request: "Transkript Talebi",
  certificate_request: "Sertifika Talebi",
  enrollment_letter: "Kayıt Belgesi Talebi",
  general_question: "Genel Soru",
  complaint: "Şikayet",
  grade_objection: "Not İtirazı",
  leave_of_absence: "İzin/Kayıt Dondurma",
};

export default function IncomingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [email, setEmail] = useState<IncomingEmail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [replySubject, setReplySubject] = useState("");
  const [replyBody, setReplyBody] = useState("");
  const [adminNotes, setAdminNotes] = useState("");

  useEffect(() => {
    api.getIncoming(id).then((ie) => {
      setEmail(ie);
      setReplySubject(ie.reply_subject ?? "");
      setReplyBody(ie.reply_body ?? "");
      setAdminNotes(ie.admin_notes ?? "");
      setLoading(false);
    });
  }, [id]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await api.updateIncoming(id, {
        reply_subject: replySubject,
        reply_body: replyBody,
        admin_notes: adminNotes,
      });
      setEmail(updated);
      alert("Kaydedildi.");
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setSaving(false);
    }
  };

  const handleApprove = async () => {
    if (!confirm("Yanıtı onaylıyor ve öğrenciye gönderiyorsunuz. Devam?")) return;
    // Onaydan önce düzenlemeleri (admin notu dahil) kaydet, aksi halde
    // admin notu DB'ye yazılmadan gönderim başlar.
    try {
      await api.updateIncoming(id, {
        reply_subject: replySubject,
        reply_body: replyBody,
        admin_notes: adminNotes,
      });
    } catch (e) {
      alert(e instanceof Error ? e.message : "Kaydetme hatası — onay iptal edildi");
      return;
    }
    await api.approveIncoming(id);
    router.push("/incoming");
  };

  const handleSkip = async () => {
    const reason = window.prompt("Atlama nedeni (opsiyonel):");
    await api.skipIncoming(id, reason || undefined);
    router.push("/incoming");
  };

  const handleRetry = async () => {
    await api.retryIncoming(id);
    router.push("/incoming");
  };

  const handleReanalyze = async () => {
    await api.reanalyzeIncoming(id);
    router.push("/incoming");
  };

  if (loading)
    return (
      <div className="flex justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
      </div>
    );
  if (!email)
    return <div className="text-center py-16 text-gray-400">E-posta bulunamadı.</div>;

  const statusCfg = STATUS_CONFIG[email.status] ?? STATUS_CONFIG.RECEIVED;
  const isEditable = email.status === "PENDING_REVIEW";

  return (
    <div className="max-w-4xl">
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-sm text-slate-500 hover:text-primary-700 mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Geri
      </button>

      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-bold text-primary-900">Gelen E-posta Detayı</h1>
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
            Otomatik Onaylandı (Pilot Modu)
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Sol: Gelen E-posta */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
          <h2 className="text-sm font-semibold text-slate-700 mb-4 uppercase tracking-wide">
            Gelen E-posta
          </h2>

          <div className="space-y-4">
            <div>
              <span className="text-xs text-slate-500">Gönderen</span>
              <p className="text-sm text-gray-900">
                {email.sender_name || `#${email.sender_email_hash.slice(0, 8)}`}
              </p>
            </div>
            <div>
              <span className="text-xs text-slate-500">Konu</span>
              <p className="text-sm font-medium text-gray-900">
                {email.subject || "(konu yok)"}
              </p>
            </div>
            <div>
              <span className="text-xs text-slate-500">İçerik</span>
              <pre className="text-sm text-gray-700 whitespace-pre-wrap bg-slate-50 rounded-lg p-3 mt-1 max-h-64 overflow-y-auto font-sans">
                {email.body_text || "(içerik yok)"}
              </pre>
            </div>

            {email.has_attachments && (
              <div>
                <span className="text-xs text-slate-500">Ekler</span>
                <p className="text-sm text-gray-600">
                  {JSON.parse(email.attachment_names_json).join(", ") || "Ek dosyalar var"}
                </p>
              </div>
            )}

            {email.intent_type && (
              <div className="flex gap-4">
                <div>
                  <span className="text-xs text-slate-500">Tespit Edilen Talep</span>
                  <p className="text-sm text-primary-700 font-medium">
                    {INTENT_LABELS[email.intent_type] ?? email.intent_type}
                  </p>
                </div>
                {email.intent_confidence != null && (
                  <div>
                    <span className="text-xs text-slate-500">Güven</span>
                    <p className="text-sm text-gray-700">
                      %{(email.intent_confidence * 100).toFixed(0)}
                    </p>
                  </div>
                )}
              </div>
            )}

            {email.rag_context_preview && (
              <div>
                <span className="text-xs text-slate-500">
                  İlgili Yönetmelik ({email.rag_source_count} kaynak)
                </span>
                <pre className="text-xs text-gray-600 whitespace-pre-wrap bg-blue-50 rounded-lg p-3 mt-1 max-h-40 overflow-y-auto font-sans">
                  {email.rag_context_preview}
                </pre>
              </div>
            )}
          </div>
        </div>

        {/* Sağ: AI Yanıtı */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
          <h2 className="text-sm font-semibold text-slate-700 mb-4 uppercase tracking-wide">
            AI Yanıtı
          </h2>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-500 mb-1.5 uppercase tracking-wide">
                Yanıt Konusu
              </label>
              <input
                type="text"
                value={replySubject}
                onChange={(e) => setReplySubject(e.target.value)}
                disabled={!isEditable}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-50 disabled:text-slate-400"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-500 mb-1.5 uppercase tracking-wide">
                Yanıt İçeriği
              </label>
              <textarea
                value={replyBody}
                onChange={(e) => setReplyBody(e.target.value)}
                disabled={!isEditable}
                rows={12}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-50 disabled:text-slate-400 resize-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-500 mb-1.5 uppercase tracking-wide">
                Admin Notu
              </label>
              <textarea
                value={adminNotes}
                onChange={(e) => setAdminNotes(e.target.value)}
                disabled={!isEditable}
                rows={2}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-50 disabled:text-slate-400 resize-none"
              />
            </div>

            {/* Aksiyonlar */}
            {isEditable && (
              <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
                >
                  {saving ? "Kaydediliyor..." : "Kaydet"}
                </button>
                <div className="flex gap-2">
                  <button
                    onClick={handleSkip}
                    className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors"
                  >
                    <SkipForward className="w-4 h-4" />
                    Atla
                  </button>
                  <button
                    onClick={handleApprove}
                    className="flex items-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
                  >
                    <CheckCircle className="w-4 h-4" />
                    Onayla ve Gönder
                  </button>
                </div>
              </div>
            )}

            {email.status === "FAILED" && (
              <div className="pt-4 border-t border-slate-100">
                <p className="text-sm text-red-600 mb-3">
                  Gönderim hatası: {email.last_error}
                </p>
                <button
                  onClick={handleRetry}
                  className="flex items-center gap-1.5 rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 transition-colors"
                >
                  <RotateCcw className="w-4 h-4" />
                  Yeniden Dene
                </button>
              </div>
            )}

            {email.status === "ANALYSIS_FAILED" && (
              <div className="pt-4 border-t border-slate-100">
                <p className="text-sm text-red-600 mb-3">
                  Analiz hatası: {email.last_error}
                </p>
                <button
                  onClick={handleReanalyze}
                  className="flex items-center gap-1.5 rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600 transition-colors"
                >
                  <RotateCcw className="w-4 h-4" />
                  Yeniden Analiz Et
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
