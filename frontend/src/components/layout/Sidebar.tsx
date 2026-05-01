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
    <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-primary-900">
      {/* Logo */}
      <div className="flex items-center justify-center px-6 py-5 border-b border-primary-800">
        <Image
          src="/LOGO.jpeg"
          alt="Logo"
          width={160}
          height={60}
          className="object-contain max-h-14"
          priority
        />
      </div>

      {/* Navigasyon */}
      <nav className="flex-1 overflow-y-auto py-5 px-3">
        <p className="px-3 mb-2 text-primary-400 text-xs font-semibold uppercase tracking-wider">
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
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all",
                    active
                      ? "bg-primary-700 text-white shadow-sm"
                      : "text-primary-200 hover:bg-primary-800 hover:text-white"
                  )}
                >
                  <Icon className="w-5 h-5 flex-shrink-0" />
                  <span className="flex-1">{label}</span>
                  {badge > 0 && (
                    <span className="inline-flex items-center justify-center min-w-[20px] h-5 rounded-full bg-red-500 px-1.5 text-[11px] font-bold text-white leading-none">
                      {badge > 99 ? "99+" : badge}
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Kullanıcı + Çıkış */}
      <div className="border-t border-primary-800 p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 rounded-full bg-primary-700 flex items-center justify-center flex-shrink-0">
            <span className="text-white text-xs font-bold">A</span>
          </div>
          <div className="min-w-0">
            <p className="text-white text-sm font-medium leading-tight">Admin</p>
            <p className="text-primary-300 text-xs">Yönetici</p>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-primary-300 hover:bg-primary-800 hover:text-white transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Çıkış Yap
        </button>
      </div>
    </aside>
  );
}
