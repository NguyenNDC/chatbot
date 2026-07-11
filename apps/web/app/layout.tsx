import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Enterprise Chatbot Graph RAG",
  description: "Dashboard van hanh cho tenant, ingest, retrieval, graph va answer policy.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi">
      <body>
        <div className="app-frame">
          <header className="topbar">
            <div>
              <div className="eyebrow">Enterprise Chatbot Graph RAG</div>
              <strong className="brand-title">Operations Console</strong>
            </div>
            <nav className="topnav">
              <Link href="/dashboard">Dashboard</Link>
              <Link href="/tenants">Quan ly tenant</Link>
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
