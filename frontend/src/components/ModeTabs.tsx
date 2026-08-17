"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { forgetMe } from "@/lib/api";
import { forgetAnonId } from "@/lib/identity";
import { AuthControl } from "@/components/AuthControl";

interface Props {
  active: "chat" | "lore" | "arc" | "make";
}

async function handleForgetMe() {
  if (!window.confirm("Forget your MemeGPT identity and history? This can't be undone.")) {
    return;
  }
  await forgetMe().catch(() => {});
  forgetAnonId();
  window.location.reload();
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Shared header + Chat|Lore tab toggle. The URL is the source of truth for
 * which surface is active (/chat = Chat, /lore = Lore) rather than internal
 * client state — this is what makes /lore a genuine, refreshable,
 * bookmarkable deep link, and what Phase 3's share-target redirect lands on.
 * / is the public marketing landing page, not one of these two tabs.
 *
 * Tab clicks are wrapped in document.startViewTransition() when the
 * browser supports it and prefers-reduced-motion isn't set — the plain
 * browser API, not a Next.js feature: Next 14 on React 18 has no native
 * View Transitions integration (that needs React 19's <ViewTransition>
 * primitive). Link's real href is kept untouched so modified clicks
 * (cmd/ctrl/middle-click "open in new tab") and keyboard/hover behavior
 * are unaffected — only a plain left-click gets intercepted. Known rough
 * edge, not swept under the rug: startViewTransition expects its callback
 * to resolve once the DOM has actually updated, but router.push() here is
 * an async App Router navigation, not a synchronous mutation — so the
 * transition and the real navigation aren't rigorously synchronized the
 * way they would be with React 19's native support. It still works
 * (verified: navigation completes, no console errors) and looks
 * reasonable for already-prefetched routes, but isn't the polished result
 * native support would give.
 */
export function ModeTabs({ active }: Props) {
  const router = useRouter();

  function navigate(e: React.MouseEvent<HTMLAnchorElement>, href: string) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    if (!document.startViewTransition || prefersReducedMotion()) {
      router.push(href);
      return;
    }
    document.startViewTransition(() => {
      router.push(href);
    });
  }

  return (
    <header className="shrink-0 flex items-center justify-between px-4 py-3
                       border-b border-border bg-background/80 backdrop-blur-sm">
      <Link href="/" className="block">
        <h1 className="caption caption-mark text-xl leading-none">
          MemeGPT
        </h1>
        <p className="text-[11px] text-gray-600 mt-0.5">
          {active === "chat"
            ? "Talk to it like any chatbot. It only speaks meme."
            : active === "lore"
            ? "Drop the lore. Get the highlight reel."
            : active === "arc"
            ? "Your meme era, scored in aura."
            : "Pick a template. Write your own captions."}
        </p>
      </Link>
      <div className="flex items-center gap-3">
        <nav className="flex items-center gap-1 bg-card border border-border rounded-full p-1">
          <Link
            href="/chat"
            onClick={(e) => navigate(e, "/chat")}
            className={`text-xs font-medium rounded-full px-3 py-1.5 transition-colors ${
              active === "chat"
                ? "bg-accent text-white"
                : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
            }`}
          >
            Chat
          </Link>
          <Link
            href="/lore"
            onClick={(e) => navigate(e, "/lore")}
            className={`text-xs font-medium rounded-full px-3 py-1.5 transition-colors ${
              active === "lore"
                ? "bg-accent text-white"
                : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
            }`}
          >
            Lore
          </Link>
          <Link
            href="/make"
            onClick={(e) => navigate(e, "/make")}
            className={`text-xs font-medium rounded-full px-3 py-1.5 transition-colors ${
              active === "make"
                ? "bg-accent text-white"
                : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
            }`}
          >
            Make
          </Link>
          <Link
            href="/arc"
            onClick={(e) => navigate(e, "/arc")}
            className={`text-xs font-medium rounded-full px-3 py-1.5 transition-colors ${
              active === "arc"
                ? "bg-accent text-white"
                : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
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
