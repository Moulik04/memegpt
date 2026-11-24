import type { Metadata } from "next";
import Link from "next/link";
import { Masthead } from "@/components/Masthead";
import { MemeDisplay } from "@/components/MemeDisplay";

export const metadata: Metadata = {
  title: "Page not found",
};

/** The copy deck, section 7.8. */
export default function NotFound() {
  return (
    <div className="min-h-dvh flex flex-col bg-background">
      <Masthead variant="system" />
      <main className="flex-1 mx-auto w-full max-w-6xl px-4 md:px-8 py-8 md:py-12 flex flex-col items-start gap-5">
        <h1 className="font-display text-[length:var(--text-title)] leading-[0.95] text-foreground">404: not a page.</h1>
        <p className="text-lg text-foreground">Whatever you were looking for isn&apos;t here. The chatbot is, though.</p>
        <MemeDisplay
          url="/landing/404_example.png"
          alt="Is This a Pigeon meme: a confused man asking 'is this a page?'"
          className="flex justify-start max-w-full"
          maxHeightClassName="max-h-[50vh]"
        />
        <Link
          href="/chat"
          className="inline-flex items-center min-h-12 px-6 rounded-sm bg-primary text-primary-foreground text-base
                     font-semibold hover:bg-primary/85 transition-colors duration-[var(--duration-fast)]"
        >
          Open MemeGPT
        </Link>
      </main>
    </div>
  );
}
