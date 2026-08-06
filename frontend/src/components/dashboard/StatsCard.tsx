import type { LucideIcon } from "lucide-react";

interface StatsCardProps {
  label: string;
  value: number | string;
  icon: LucideIcon;
  highlight?: boolean;
}

export function StatsCard({ label, value, icon: Icon, highlight }: StatsCardProps) {
  return (
    <div
      className={`rounded-2xl border p-5 bg-white shadow-sm transition-all hover:shadow-md ${
        highlight
          ? "border-orange-200 bg-gradient-to-br from-orange-50 to-white"
          : "border-slate-200 hover:border-primary-200"
      }`}
    >
      <div className="flex items-start justify-between mb-4">
        <div
          className={`w-10 h-10 rounded-xl flex items-center justify-center ${
            highlight
              ? "bg-orange-100 ring-1 ring-orange-200"
              : "bg-primary-50 ring-1 ring-primary-100"
          }`}
        >
          <Icon
            className={`w-5 h-5 ${highlight ? "text-orange-500" : "text-primary-600"}`}
          />
        </div>
      </div>
      <p
        className={`text-3xl font-bold tracking-tight mb-1 ${
          highlight ? "text-orange-600" : "text-primary-900"
        }`}
      >
        {value}
      </p>
      <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">{label}</span>
    </div>
  );
}
