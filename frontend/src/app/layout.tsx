import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "UniBox Admin",
  description: "Üniversite AI Asistanı Admin Dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr" suppressHydrationWarning>
      <body suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
