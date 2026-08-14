"use client";

import { useState } from "react";
import { ShieldCheck, Zap, AlertTriangle } from "lucide-react";
import clsx from "clsx";
import { useSystemMode } from "@/hooks/useSystemMode";
import type { SystemMode } from "@/types";

const MODE_INFO: Record<
  SystemMode,
  { title: string; description: string; icon: typeof Zap; accent: string }
> = {
  CO_PILOT: {
    title: "Co-Pilot Modu",
    description:
      "AI, gelen öğrenci e-postalarına yanıt taslağı hazırlar. Yanıt öğrenciye gönderilmeden önce memur panelden inceler, isterse düzenler ve onaylar.",
    icon: ShieldCheck,
    accent: "emerald",
  },
  PILOT: {
    title: "Pilot Modu",
    description:
      "AI, gelen öğrenci e-postalarına ürettiği yanıtı insan onayı olmadan doğrudan SMTP üzerinden gönderir. Hiçbir inceleme adımı yoktur.",
    icon: Zap,
    accent: "red",
  },
};

export default function SettingsPage() {
  const { mode, saving, setMode } = useSystemMode();
  const [pendingMode, setPendingMode] = useState<SystemMode | null>(null);

  const requestModeChange = (target: SystemMode) => {
    if (target === mode) return;
    setPendingMode(target);
  };

  const confirmModeChange = async () => {
    if (!pendingMode) return;
    try {
      await setMode(pendingMode);
    } finally {
      setPendingMode(null);
    }
  };

  return (
    <div className="max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-primary-900">Ayarlar</h1>
        <p className="text-slate-500 mt-1 text-sm">
          Sistemin gelen öğrenci e-postalarına nasıl yanıt vereceğini belirleyin.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 mb-6">
        <h2 className="text-sm font-semibold text-slate-700 mb-1 uppercase tracking-wide">
          Çalışma Modu
        </h2>
        <p className="text-sm text-slate-500 mb-5">
          Bu ayar sistemin tamamını (global) etkiler ve yalnızca gelen e-posta yanıtlama
          akışını kapsar. Giden e-posta (chatbot) onay akışı bu ayardan etkilenmez.
        </p>

        {mode === null ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary-600" />
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {(Object.keys(MODE_INFO) as SystemMode[]).map((key) => {
              const info = MODE_INFO[key];
              const Icon = info.icon;
              const active = mode === key;
              return (
                <button
                  key={key}
                  onClick={() => requestModeChange(key)}
                  disabled={saving}
                  className={clsx(
                    "text-left rounded-xl border-2 p-4 transition-colors disabled:opacity-50",
                    active
                      ? info.accent === "red"
                        ? "border-red-400 bg-red-50"
                        : "border-emerald-400 bg-emerald-50"
                      : "border-slate-200 hover:border-slate-300 bg-white"
                  )}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Icon
                      className={clsx(
                        "w-4 h-4",
                        active
                          ? info.accent === "red"
                            ? "text-red-600"
                            : "text-emerald-600"
                          : "text-slate-400"
                      )}
                    />
                    <span className="font-semibold text-sm text-slate-900">
                      {info.title}
                    </span>
                    {active && (
                      <span
                        className={clsx(
                          "ml-auto text-[10px] font-bold uppercase tracking-wide rounded-full px-2 py-0.5",
                          info.accent === "red"
                            ? "bg-red-100 text-red-700"
                            : "bg-emerald-100 text-emerald-700"
                        )}
                      >
                        Aktif
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-600 leading-relaxed">
                    {info.description}
                  </p>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {pendingMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
            <div className="flex items-start gap-3 mb-4">
              <div
                className={clsx(
                  "flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center",
                  pendingMode === "PILOT" ? "bg-red-100" : "bg-emerald-100"
                )}
              >
                <AlertTriangle
                  className={clsx(
                    "w-5 h-5",
                    pendingMode === "PILOT" ? "text-red-600" : "text-emerald-600"
                  )}
                />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900">
                  {MODE_INFO[pendingMode].title}&apos;na geçilsin mi?
                </h3>
                <p className="text-sm text-slate-500 mt-1">
                  {pendingMode === "PILOT"
                    ? "Bu andan itibaren gelen e-postalara AI yanıtları hiçbir memur incelemesi olmadan otomatik gönderilecek. KVKK ve denetim açısından bu kararın sorumluluğunu üstlendiğinizi onaylıyor musunuz?"
                    : "Gelen e-postalara üretilen AI yanıtları tekrar memur onayı bekleyecek, otomatik gönderim durdurulacak."}
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setPendingMode(null)}
                disabled={saving}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Vazgeç
              </button>
              <button
                onClick={confirmModeChange}
                disabled={saving}
                className={clsx(
                  "rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50",
                  pendingMode === "PILOT"
                    ? "bg-red-600 hover:bg-red-700"
                    : "bg-emerald-600 hover:bg-emerald-700"
                )}
              >
                {saving ? "Uygulanıyor..." : "Onayla"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
