import type { EmailDraftStatus } from "@/types";
import clsx from "clsx";

const STATUS_CONFIG: Record<
  EmailDraftStatus,
  { label: string; className: string }
> = {
  IDLE: { label: "Boş", className: "bg-gray-100 text-gray-600" },
  COLLECTING_INFO: { label: "Bilgi Toplanıyor", className: "bg-blue-100 text-blue-700" },
  DRAFT_CREATED: { label: "Taslak Oluştu", className: "bg-indigo-100 text-indigo-700" },
  PENDING_APPROVAL: { label: "Onay Bekliyor", className: "bg-orange-100 text-orange-700" },
  APPROVED: { label: "Onaylandı", className: "bg-green-100 text-green-700" },
  REJECTED: { label: "Reddedildi", className: "bg-red-100 text-red-700" },
  SENT: { label: "Gönderildi", className: "bg-emerald-100 text-emerald-700" },
  FAILED: { label: "Hata", className: "bg-red-100 text-red-700" },
  CANCELLED: { label: "İptal", className: "bg-gray-100 text-gray-500" },
};

export function StatusBadge({ status }: { status: EmailDraftStatus }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.IDLE;
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", cfg.className)}>
      {cfg.label}
    </span>
  );
}
