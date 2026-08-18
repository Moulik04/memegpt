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

const DESCRIPTION = "A chatbot that speaks exclusively in memes.";

// Every route below gets this as its default og:image/twitter:image unless
// it sets its own (the way /m/[id] already does with the actual meme being
// shared) — a real rendered caption-on-template, not a screenshot or logo.
const DEFAULT_SHARE_IMAGE = "/landing/drake_example.png";

export const metadata: Metadata = {
  metadataBase: new URL("https://memegpt-six.vercel.app"),
  title: {
    default: "MemeGPT — A chatbot that only speaks meme.",
    template: "%s — MemeGPT",
  },
  description: DESCRIPTION,
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "MemeGPT",
  },
  openGraph: {
    title: "MemeGPT — A chatbot that only speaks meme.",
    description: DESCRIPTION,
    images: [{ url: DEFAULT_SHARE_IMAGE }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "MemeGPT — A chatbot that only speaks meme.",
    description: DESCRIPTION,
    images: [DEFAULT_SHARE_IMAGE],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
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
