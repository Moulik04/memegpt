import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MemeCard } from "@/components/MemeCard";

// Server-side backend calls use BACKEND_URL (matches the existing route.ts
// convention — may be a Docker-internal/localhost address). The image URL
// embedded in og:image must be reachable by external crawlers (Discord,
// Twitter, iMessage), so that one comes straight from the backend's own
// response (already an R2 public URL or Render's public /static/ URL) or,
// for a relative /static/ path, gets prefixed with the public-facing base.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const PUBLIC_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

interface SharedMeme {
  url: string;
  template_name: string | null;
}

async function fetchMeme(id: string): Promise<SharedMeme | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/memes/${id}`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

function publicMemeUrl(url: string): string {
  return url.startsWith("http") ? url : `${PUBLIC_API_BASE}${url}`;
}

interface Props {
  params: { id: string };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const meme = await fetchMeme(params.id);
  if (!meme) {
    return { title: "Meme not found — MemeGPT" };
  }

  const title = meme.template_name ? `${meme.template_name}, made with MemeGPT` : "A meme, made with MemeGPT";
  const description = "MemeGPT is a chatbot that only replies in memes. Make your own.";
  const imageUrl = publicMemeUrl(meme.url);

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      images: [{ url: imageUrl }],
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [imageUrl],
    },
  };
}

export default async function SharedMemePage({ params }: Props) {
  const meme = await fetchMeme(params.id);
  if (!meme) {
    notFound();
  }

  const imageUrl = publicMemeUrl(meme.url);

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-6 py-12 gap-8">
      <Link href="/" className="text-xl font-extrabold tracking-tight gradient-text">
        MemeGPT
      </Link>

      <div className="max-w-md w-full">
        <MemeCard url={imageUrl} alt={meme.template_name ?? "A meme made with MemeGPT"} large />
      </div>

      <div className="text-center">
        <p className="text-sm text-gray-500 mb-4">Made with MemeGPT. It only replies in memes.</p>
        <Link
          href="/chat"
          className="inline-block bg-brand-600 hover:bg-brand-500 transition-colors text-white
                     font-semibold rounded-full px-8 py-3.5 text-base shadow-lg shadow-brand-900/40"
        >
          Make your own
        </Link>
      </div>
    </div>
  );
}
