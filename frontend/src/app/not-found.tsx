import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-6 py-12 gap-8 text-center">
      <Link href="/" className="caption caption-mark text-xl">
        MemeGPT
      </Link>

      <div className="w-full max-w-sm rounded-2xl bg-card border border-border p-3 shadow-2xl shadow-black/50">
        <Image
          src="/landing/404_example.png"
          alt="Is This a Pigeon meme: a confused man asking 'is this a page?'"
          width={600}
          height={600}
          className="w-full h-auto rounded-xl"
          priority
        />
      </div>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">404: not a page.</h1>
        <p className="mt-2 text-sm text-gray-500">
          Whatever you were looking for isn&apos;t here. The chatbot is, though.
        </p>
      </div>

      <Link
        href="/chat"
        className="bg-accent hover:bg-accent/90 transition-colors text-white font-semibold
                   rounded-full px-8 py-3.5 text-base shadow-lg"
      >
        Open MemeGPT
      </Link>
    </div>
  );
}
