"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle, XCircle, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import type { EmailDraft } from "@/types";
import { StatusBadge } from "@/components/emails/StatusBadge";

export default function DraftDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [draft, setDraft] = useState<EmailDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [recipientEmail, setRecipientEmail] = useState("");
  const [adminNotes, setAdminNotes] = useState("");

  useEffect(() => {
    api.getDraft(id).then((d) => {
      setDraft(d);
      setSubject(d.subject ?? "");
      setBody(d.body ?? "");
      setRecipientEmail(d.recipient_email ?? "");
      setAdminNotes(d.admin_notes ?? "");
      setLoading(false);
    });
  }, [id]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await api.updateDraft(id, {
        subject,
        body,
        recipient_email: recipientEmail,
        admin_notes: adminNotes,
      });
      setDraft(updated);
      alert("Kaydedildi.");
    } catch (e) {
      alert(e instanceof Error ? e.message : "Hata");
    } finally {
      setSaving(false);
    }
  };

  const handleApprove = async () => {
    if (!confirm("Taslağı onaylıyor ve gönderim kuyruğuna ekliyorsunuz. Devam?")) return;
    await api.approveDraft(id);
    router.push("/emails");
  };

  const handleReject = async () => {
    const reason = window.prompt("Red nedeni:");
    if (!reason) return;
    await api.rejectDraft(id, reason);
    router.push("/emails");
  };

  const handleRetry = async () => {
    await api.retryDraft(id);
    router.push("/emails");
  };

  if (loading) return <div className="flex justify-center py-16"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" /></div>;
  if (!draft) return <div className="text-center py-16 text-gray-400">Taslak bulunamadı.</div>;

  const isEditable = draft.status === "PENDING_APPROVAL" || draft.status === "DRAFT_CREATED";

  return (
    <div className="max-w-3xl">
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-sm text-slate-500 hover:text-primary-700 mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Geri
      </button>

      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-bold text-primary-900">E-posta Taslağı</h1>
        <StatusBadge status={draft.status} />
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-5">
        {/* Alıcı */}
        <div>
          <label className="block text-xs font-semibold text-slate-500 mb-1.5 uppercase tracking-wide">
            Alıcı E-posta
          </label>
          <input
            type="email"
            value={recipientEmail}
            onChange={(e) => setRecipientEmail(e.target.value)}
            disabled={!isEditable}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-50 disabled:text-slate-400"
          />
        </div>

        {/* Konu */}
        <div>
          <label className="block text-xs font-semibold text-slate-500 mb-1.5 uppercase tracking-wide">
            Konu
          </label>
          <input
            type="text"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            disabled={!isEditable}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-50 disabled:text-slate-400"
          />
        </div>

        {/* İçerik */}
        <div>
          <label className="block text-xs font-semibold text-slate-500 mb-1.5 uppercase tracking-wide">
            İçerik
          </label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            disabled={!isEditable}
            rows={12}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-50 disabled:text-slate-400 resize-none"
          />
        </div>

        {/* Admin Notu */}
        <div>
          <label className="block text-xs font-semibold text-slate-500 mb-1.5 uppercase tracking-wide">
            Admin Notu (iç kullanım)
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
                onClick={handleReject}
                className="flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-100 transition-colors"
              >
                <XCircle className="w-4 h-4" />
                Reddet
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

        {draft.status === "FAILED" && (
          <div className="pt-4 border-t border-slate-100">
            <p className="text-sm text-red-600 mb-3">
              Gönderim hatası: {draft.last_error}
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

        {draft.rejection_reason && (
          <div className="rounded-lg bg-red-50 border border-red-200 p-3">
            <p className="text-sm font-medium text-red-700">Red Nedeni:</p>
            <p className="text-sm text-red-600">{draft.rejection_reason}</p>
          </div>
        )}
      </div>
    </div>
  );
}
