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
      className={`rounded-xl border p-5 bg-white shadow-sm transition-all ${
        highlight
          ? "border-orange-200 bg-orange-50"
          : "border-slate-200 hover:border-primary-200"
      }`}
    >
      <div className="flex items-center justify-between mb-4">
        <div
          className={`w-10 h-10 rounded-lg flex items-center justify-center ${
            highlight ? "bg-orange-100" : "bg-primary-50"
          }`}
        >
          <Icon
            className={`w-5 h-5 ${highlight ? "text-orange-500" : "text-primary-600"}`}
          />
        </div>
      </div>
      <p
        className={`text-3xl font-bold mb-1 ${
          highlight ? "text-orange-600" : "text-primary-900"
        }`}
      >
        {value}
      </p>
      <span className="text-sm font-medium text-slate-500">{label}</span>
    </div>
  );
}
