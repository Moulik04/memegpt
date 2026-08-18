"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-6 py-12 gap-8 text-center">
      <Link href="/" className="caption caption-mark text-xl">
        MemeGPT
      </Link>

      <div className="w-full max-w-lg rounded-2xl bg-card border border-border p-3 shadow-2xl shadow-black/50">
        <Image
          src="/landing/500_example.png"
          alt="This Is Fine meme: a dog sitting in a burning room, captioned 'the server, right now'"
          width={1200}
          height={600}
          className="w-full h-auto rounded-xl"
          priority
        />
      </div>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Something broke.</h1>
        <p className="mt-2 text-sm text-gray-500">
          Not you — us. Try again in a moment.
        </p>
      </div>

      <div className="flex flex-col sm:flex-row items-center gap-3">
        <button
          type="button"
          onClick={reset}
          className="bg-accent hover:bg-accent/90 transition-colors text-white font-semibold
                     rounded-full px-8 py-3.5 text-base shadow-lg"
        >
          Try again
        </button>
        <Link
          href="/"
          className="bg-white/5 hover:bg-white/10 border border-border hover:border-gray-700
                     transition-colors text-gray-200 font-semibold rounded-full px-8 py-3.5 text-base"
        >
          Back home
        </Link>
      </div>
    </div>
  );
}
