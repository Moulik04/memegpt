import type { Metadata } from "next";
import Link from "next/link";
import { Masthead } from "@/components/Masthead";
import { notFound } from "next/navigation";
import { MemeDisplay } from "@/components/MemeDisplay";

// Server-side backend calls use BACKEND_URL (matches the existing route.ts
// convention — may be a Docker-internal/localhost address). The image URL
// embedded in og:image must be reachable by external crawlers (Discord,
// Twitter, iMessage), so that one comes straight from the backend's own
// response (already an R2 public URL or Render's public /static/ URL) or,
// for a relative /static/ path, gets prefixed with the public-facing base.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const PUBLIC_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** The copy deck, section 7.8. */
const MADE_WITH = "Made with MemeGPT. It only replies in memes.";
const MAKE_YOUR_OWN = "Make your own";

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
    return { title: "Meme not found" };
  }

  const title = meme.template_name ? `${meme.template_name}, made with MemeGPT` : "A meme, made with MemeGPT";
  const description = MADE_WITH;
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
    <div className="min-h-dvh flex flex-col bg-background">
      <Masthead variant="system" />
      <main className="flex-1 mx-auto w-full max-w-6xl px-4 md:px-8 py-8 md:py-12 flex flex-col items-center gap-6">
        <h1 className="sr-only">{meme.template_name ? `${meme.template_name}, made with MemeGPT` : "A meme made with MemeGPT"}</h1>
        <MemeDisplay
          url={imageUrl}
          alt={meme.template_name ?? "A meme made with MemeGPT"}
          className="flex justify-center max-w-full"
          maxHeightClassName="max-h-[70vh]"
        />
        <div className="flex flex-col items-center gap-4 text-center">
          <p className="text-lg text-foreground">{MADE_WITH}</p>
          <Link
            href="/chat"
            className="inline-flex items-center min-h-12 px-6 rounded-sm bg-primary text-primary-foreground text-base
                       font-semibold hover:bg-primary/85 transition-colors duration-[var(--duration-fast)]"
          >
            {MAKE_YOUR_OWN}
          </Link>
        </div>
      </main>
    </div>
  );
}
