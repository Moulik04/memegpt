import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { GoogleAnalytics } from "@next/third-parties/google";
import { AuthProvider } from "@/lib/AuthProvider";
import "./globals.css";

// Committed WOFF2 subsets, built from backend/fonts by
// scripts/build_web_fonts.py, so the build never fetches a font and the
// site matches the server-rendered Arc card. Licenses sit beside them.
// Archivo is one variable file covering weights 400 to 800.
const anton = localFont({
  src: "./fonts/anton.woff2",
  weight: "400",
  variable: "--font-anton",
  fallback: ["Impact", "sans-serif"],
});
const archivo = localFont({
  src: "./fonts/archivo.woff2",
  weight: "400 800",
  variable: "--font-archivo",
  fallback: ["Arial", "sans-serif"],
});

const DESCRIPTION = "A chatbot that speaks exclusively in memes.";

// Every route below gets this as its default og:image/twitter:image unless
// it sets its own (the way /m/[id] already does with the actual meme being
// shared) — a real rendered caption-on-template, not a screenshot or logo.
const DEFAULT_SHARE_IMAGE = "/landing/drake_example.png";

export const metadata: Metadata = {
  metadataBase: new URL("https://memegpt.app"),
  title: {
    default: "MemeGPT — A chatbot that only speaks meme.",
    template: "%s — MemeGPT",
  },
  description: DESCRIPTION,
  manifest: "/manifest.json",
  // Rendered by scripts/render_icons.py. The installed app's icons are in
  // manifest.json.
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "48x48" },
      { url: "/icon-192.png", type: "image/png", sizes: "192x192" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
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
  const gaId = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;

  return (
    <html
      lang="en"
      className={`dark font-sans ${anton.variable} ${archivo.variable}`}
    >
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
      {gaId && <GoogleAnalytics gaId={gaId} />}
    </html>
  );
}
