"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { WsProvider } from "@/contexts/WsContext";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("unibox_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    setMounted(true);
  }, [router]);

  if (!mounted) {
    return null;
  }

  return (
    <WsProvider>
      <div className="flex min-h-screen bg-slate-100">
        <Sidebar />
        <main className="flex-1 ml-64 min-h-screen">
          <div className="max-w-7xl mx-auto px-8 py-8">
            {children}
          </div>
        </main>
      </div>
    </WsProvider>
  );
}
