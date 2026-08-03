"use client";

import Link from "next/link";
import { forgetMe } from "@/lib/api";
import { forgetAnonId } from "@/lib/identity";
import { AuthControl } from "@/components/AuthControl";

interface Props {
  active: "chat" | "lore" | "arc";
}

async function handleForgetMe() {
  if (!window.confirm("Forget your MemeGPT identity and history? This can't be undone.")) {
    return;
  }
  await forgetMe().catch(() => {});
  forgetAnonId();
  window.location.reload();
}

/**
 * Shared header + Chat|Lore tab toggle. The URL is the source of truth for
 * which surface is active (/chat = Chat, /lore = Lore) rather than internal
 * client state — this is what makes /lore a genuine, refreshable,
 * bookmarkable deep link, and what Phase 3's share-target redirect lands on.
 * / is the public marketing landing page, not one of these two tabs.
 */
export function ModeTabs({ active }: Props) {
  return (
    <header className="shrink-0 flex items-center justify-between px-4 py-3
                       border-b border-gray-800/60 bg-gray-950/80 backdrop-blur-sm">
      <Link href="/" className="block">
        <h1 className="text-xl font-extrabold tracking-tight gradient-text leading-none">
          MemeGPT
        </h1>
        <p className="text-[11px] text-gray-600 mt-0.5">
          {active === "chat"
            ? "Talk to it like any chatbot. It only speaks meme."
            : active === "lore"
            ? "Drop the lore. Get the highlight reel."
            : "Your meme era, scored in aura."}
        </p>
      </Link>
      <div className="flex items-center gap-3">
        <nav className="flex items-center gap-1 bg-[#13131e] border border-gray-800 rounded-full p-1">
          <Link
            href="/chat"
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
          <Link
            href="/arc"
            className={`text-xs font-medium rounded-full px-3 py-1.5 transition-colors ${
              active === "arc"
                ? "bg-brand-600 text-white"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            Arc
          </Link>
        </nav>
        <AuthControl />
        <button
          type="button"
          onClick={handleForgetMe}
          title="Erase your MemeGPT identity, memory, and history from this device"
          className="text-[11px] text-gray-600 hover:text-gray-400 transition-colors"
        >
          Forget me
        </button>
      </div>
    </header>
  );
}
