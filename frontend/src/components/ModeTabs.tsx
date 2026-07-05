"use client";

import Link from "next/link";

interface Props {
  active: "chat" | "lore";
}

/**
 * Shared header + Chat|Lore tab toggle. The URL is the source of truth for
 * which surface is active (/ = Chat, /lore = Lore) rather than internal
 * client state — this is what makes /lore a genuine, refreshable,
 * bookmarkable deep link, and what Phase 3's share-target redirect lands on.
 */
export function ModeTabs({ active }: Props) {
  return (
    <header className="shrink-0 flex items-center justify-between px-4 py-3
                       border-b border-gray-800/60 bg-gray-950/80 backdrop-blur-sm">
      <div>
        <h1 className="text-xl font-extrabold tracking-tight gradient-text leading-none">
          MemeGPT
        </h1>
        <p className="text-[11px] text-gray-600 mt-0.5">
          {active === "chat"
            ? "Talk to it like any chatbot. It only speaks meme."
            : "Drop the lore. Get the highlight reel."}
        </p>
      </div>
      <nav className="flex items-center gap-1 bg-[#13131e] border border-gray-800 rounded-full p-1">
        <Link
          href="/"
          className={`text-xs font-medium rounded-full px-3 py-1.5 transition-colors ${
            active === "chat"
              ? "bg-brand-600 text-white"
              : "text-gray-500 hover:text-gray-300"
          }`}
        >
          Chat
        </Link>
        <Link
          href="/lore"
          className={`text-xs font-medium rounded-full px-3 py-1.5 transition-colors ${
            active === "lore"
              ? "bg-brand-600 text-white"
              : "text-gray-500 hover:text-gray-300"
          }`}
        >
          Lore
        </Link>
      </nav>
    </header>
  );
}
