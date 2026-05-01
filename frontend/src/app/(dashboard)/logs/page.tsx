"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EmailLog } from "@/types";
import { format } from "date-fns";
import { tr } from "date-fns/locale";
import { Shield } from "lucide-react";

export default function LogsPage() {
  const [logs, setLogs] = useState<EmailLog[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listLogs().then(setLogs).finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-primary-900">Gönderim Geçmişi</h1>
        <p className="text-slate-500 mt-1 text-sm">Onaylanan e-postaların KVKK uyumlu kaydı</p>
      </div>

      {/* KVKK uyarısı */}
      <div className="flex items-start gap-3 rounded-lg bg-blue-50 border border-blue-200 p-3 mb-6">
        <Shield className="w-4 h-4 text-blue-600 mt-0.5 flex-shrink-0" />
        <p className="text-xs text-blue-700">
          KVKK: Bu tabloda öğrenci TCKN, ad-soyad veya kişisel iletişim bilgisi bulunmaz.
          Yalnızca kurumsal alıcı adresleri ve anonim içerik kaydedilir.
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
        </div>
      ) : logs.length === 0 ? (
        <div className="text-center py-16 text-gray-400">Henüz gönderim kaydı yok.</div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-4 py-3 font-medium text-slate-500">Tarih</th>
                <th className="text-left px-4 py-3 font-medium text-slate-500">Alıcı</th>
                <th className="text-left px-4 py-3 font-medium text-slate-500">Konu</th>
                <th className="text-left px-4 py-3 font-medium text-slate-500">SMTP ID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {logs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {format(new Date(log.sent_at), "dd MMM yyyy HH:mm", { locale: tr })}
                  </td>
                  <td className="px-4 py-3 text-gray-700">{log.recipient_display}</td>
                  <td className="px-4 py-3 text-gray-700 truncate max-w-sm">{log.subject}</td>
                  <td className="px-4 py-3 text-gray-400 font-mono text-xs truncate max-w-xs">
                    {log.smtp_message_id ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
