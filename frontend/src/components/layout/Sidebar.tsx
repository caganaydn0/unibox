"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Monitor,
  Mail,
  Inbox,
  BookOpen,
  ClipboardList,
  LogOut,
} from "lucide-react";
import Image from "next/image";
import clsx from "clsx";
import { useWsContext } from "@/contexts/WsContext";

export function Sidebar() {
  const pathname = usePathname();
  const { pendingIncomingCount, pendingDraftCount } = useWsContext();

  const handleLogout = () => {
    localStorage.removeItem("unibox_token");
    localStorage.removeItem("unibox_refresh_token");
    window.location.href = "/login";
  };

  const NAV_ITEMS = [
    { href: "/", label: "Genel Bakış", icon: LayoutDashboard, badge: 0 },
    { href: "/monitoring", label: "Canlı İzleme", icon: Monitor, badge: 0 },
    { href: "/emails", label: "E-posta Onayları", icon: Mail, badge: pendingDraftCount },
    { href: "/incoming", label: "Gelen E-postalar", icon: Inbox, badge: pendingIncomingCount },
    { href: "/knowledge-base", label: "Bilgi Tabanı", icon: BookOpen, badge: 0 },
    { href: "/logs", label: "Gönderim Geçmişi", icon: ClipboardList, badge: 0 },
  ];

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-primary-950 border-r border-primary-900/50">
      {/* Logo */}
      <div className="flex items-center justify-center px-5 py-4 border-b border-white/5">
        <Image
          src="/logo.png"
          alt="UniBox Logo"
          width={200}
          height={89}
          className="object-contain"
          priority
        />
      </div>

      {/* Navigasyon */}
      <nav className="flex-1 overflow-y-auto py-5 px-3 space-y-6">
        <div>
          <p className="px-3 mb-2 text-primary-500 text-[10px] font-bold uppercase tracking-widest">
            Ana Menü
          </p>
          <ul className="space-y-0.5">
            {NAV_ITEMS.map(({ href, label, icon: Icon, badge }) => {
              const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    className={clsx(
                      "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150",
                      active
                        ? "bg-primary-600 text-white shadow-lg shadow-primary-900/40"
                        : "text-primary-300 hover:bg-white/5 hover:text-primary-100"
                    )}
                  >
                    <Icon
                      className={clsx(
                        "w-4 h-4 flex-shrink-0",
                        active ? "text-white" : "text-primary-400"
                      )}
                    />
                    <span className="flex-1 truncate">{label}</span>
                    {badge > 0 && (
                      <span className="inline-flex items-center justify-center min-w-[20px] h-5 rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white leading-none">
                        {badge > 99 ? "99+" : badge}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      </nav>

      {/* Kullanıcı + Çıkış */}
      <div className="border-t border-white/5 p-3">
        <div className="flex items-center gap-3 px-2 py-2 mb-1 rounded-lg bg-white/5">
          <div className="w-7 h-7 rounded-full bg-primary-600 flex items-center justify-center flex-shrink-0">
            <span className="text-white text-xs font-bold">A</span>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-white text-xs font-semibold leading-tight">Admin</p>
            <p className="text-primary-400 text-[10px]">Yönetici</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-primary-400 hover:bg-white/5 hover:text-white transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" />
          Çıkış Yap
        </button>
      </div>
    </aside>
  );
}
