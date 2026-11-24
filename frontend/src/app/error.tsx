"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Masthead } from "@/components/Masthead";
import { MemeDisplay } from "@/components/MemeDisplay";

/** The copy deck, section 7.8. */
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
    <div className="min-h-dvh flex flex-col bg-background">
      <Masthead variant="system" />
      <main className="flex-1 mx-auto w-full max-w-6xl px-4 md:px-8 py-8 md:py-12 flex flex-col items-start gap-5">
        <h1 className="font-display text-[length:var(--text-title)] leading-[0.95] text-foreground">Something broke.</h1>
        <p className="text-lg text-foreground">Not you. Us. Try again in a moment.</p>
        <MemeDisplay
          url="/landing/500_example.png"
          alt="This Is Fine meme: a dog sitting in a burning room, captioned 'the server, right now'"
          className="flex justify-start max-w-full"
          maxHeightClassName="max-h-[50vh]"
        />
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <button
            type="button"
            onClick={reset}
            className="min-h-12 px-6 rounded-sm bg-primary text-primary-foreground text-base font-semibold
                       hover:bg-primary/85 transition-colors duration-[var(--duration-fast)]"
          >
            Try again
          </button>
          <Link
            href="/"
            className="inline-flex items-center min-h-11 text-base font-medium text-foreground underline decoration-brand
                       decoration-2 underline-offset-4"
          >
            Back home
          </Link>
        </div>
      </main>
    </div>
  );
}
