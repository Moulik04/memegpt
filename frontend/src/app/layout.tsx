import type { Metadata, Viewport } from "next";
import { Anton } from "next/font/google";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { AuthProvider } from "@/lib/AuthProvider";
import "./globals.css";

// GeistSans/GeistMono ship pre-built, already self-hosted font files —
// independent of next/font/google's font list (which doesn't have Geist
// on this Next.js version). Anton is real self-hosting too: Next.js
// downloads it at build time and serves it same-origin, not a CDN link.
const anton = Anton({ subsets: ["latin"], weight: "400", variable: "--font-display" });

export const metadata: Metadata = {
  title: "MemeGPT",
  description: "A chatbot that speaks exclusively in memes.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "MemeGPT",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  themeColor: "#030712",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`dark font-sans ${anton.variable} ${GeistSans.variable} ${GeistMono.variable}`}
    >
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
