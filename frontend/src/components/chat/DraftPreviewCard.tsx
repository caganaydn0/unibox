import { Check, X, Mail } from "lucide-react";

interface DraftPreviewCardProps {
  subject: string;
  body: string;
  onApprove: () => void;
  onCancel: () => void;
  disabled: boolean;
}

export function DraftPreviewCard({
  subject,
  body,
  onApprove,
  onCancel,
  disabled,
}: DraftPreviewCardProps) {
  return (
    <div className="w-full rounded-2xl bg-white ring-1 ring-slate-200 shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 bg-slate-50 px-4 py-2.5 border-b border-slate-200">
        <Mail className="w-4 h-4 text-primary-600" />
        <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">
          Taslak Önizleme
        </span>
      </div>
      <div className="px-4 py-3 space-y-2">
        <div>
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-0.5">
            Konu
          </div>
          <div className="text-sm font-medium text-gray-900">{subject}</div>
        </div>
        <div>
          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-0.5">
            Gövde
          </div>
          <div className="text-sm text-gray-700 whitespace-pre-wrap">{body}</div>
        </div>
      </div>
      <div className="flex gap-2 px-4 py-3 bg-slate-50 border-t border-slate-200">
        <button
          type="button"
          onClick={onApprove}
          disabled={disabled}
          className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-primary-600 px-3 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50 transition-all"
        >
          <Check className="w-4 h-4" />
          Evet, gönder
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={disabled}
          className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-white ring-1 ring-slate-300 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 disabled:opacity-50 transition-all"
        >
          <X className="w-4 h-4" />
          Hayır, iptal
        </button>
      </div>
    </div>
  );
}
