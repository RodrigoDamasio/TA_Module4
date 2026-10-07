import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Nav from "@/components/Nav";
import PrivacyNotice from "@/components/PrivacyNotice";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Codebase RAG",
  description:
    "Ask questions about code and get answers with citations. Hybrid search, local embeddings, and a measured evaluation.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <Nav />
        <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col px-4 py-6">{children}</div>
        <footer className="mx-auto w-full max-w-7xl px-4 pb-6">
          <PrivacyNotice />
        </footer>
      </body>
    </html>
  );
}
