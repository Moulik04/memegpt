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

// The copy deck, sections 7.1 and 8.
const TITLE = "MemeGPT: a chatbot that only replies in memes";
const DESCRIPTION = "A chatbot that only replies in memes.";

// Links to the site preview the Front Page card, rendered by
// scripts/render_link_preview.py. Shared meme pages (/m/[id]) set their
// own preview: the meme itself.
const LINK_PREVIEW = {
  url: "/link-preview.png",
  width: 1200,
  height: 630,
  alt: "The group chat has a front page. A chatbot that only replies in memes.",
};

// Icons keep their names; the query makes browsers that cached the old
// dark set fetch these. Bump it whenever scripts/render_icons.py changes
// the files, here and in manifest.json.
const ICON_VERSION = "?v=2";

export const metadata: Metadata = {
  metadataBase: new URL("https://memegpt.app"),
  title: {
    default: TITLE,
    template: "%s · MemeGPT",
  },
  description: DESCRIPTION,
  manifest: `/manifest.json${ICON_VERSION}`,
  // Rendered by scripts/render_icons.py. The installed app's icons are in
  // manifest.json.
  icons: {
    icon: [
      { url: `/favicon.ico${ICON_VERSION}`, sizes: "16x16 32x32 48x48" },
      { url: `/icon-192.png${ICON_VERSION}`, type: "image/png", sizes: "192x192" },
    ],
    apple: [{ url: `/apple-touch-icon.png${ICON_VERSION}`, sizes: "180x180" }],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "MemeGPT",
  },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    images: [LINK_PREVIEW],
    type: "website",
    siteName: "MemeGPT",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: [LINK_PREVIEW],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  themeColor: "#FFFFFF",
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
      className={`font-sans ${anton.variable} ${archivo.variable}`}
    >
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
      {gaId && <GoogleAnalytics gaId={gaId} />}
    </html>
  );
}
