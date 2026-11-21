"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { forgetMe } from "@/lib/api";
import { forgetAnonId } from "@/lib/identity";
import { AuthControl } from "@/components/AuthControl";
import { navigateWithTransition } from "@/lib/viewTransition";
import { APP_TABS, type AppTab } from "@/lib/appTabs";

type Props =
  /** Chat, Lore, Make, Arc: one tab is active. */
  | { variant: "app"; active: AppTab }
  /** The landing page: tabs shown, none active. */
  | { variant: "landing" }
  /** Shared meme, privacy, 404, error, sign-in redirect: wordmark only. */
  | { variant: "system" };

async function handleForgetMe() {
  if (
    !window.confirm(
      "Forget your MemeGPT identity and history? Your memes are deleted too, so share links to them will stop working. This can't be undone.",
    )
  ) {
    return;
  }
  try {
    await forgetMe();
  } catch (err) {
    // The erase did not complete. Keep this browser's identity exactly as
    // it is, so the page doesn't reload looking fresh while data is still
    // there, and so a retry reaches the same rows.
    window.alert(err instanceof Error ? err.message : "MemeGPT couldn't erase your data. Please try again.");
    return;
  }
  forgetAnonId();
  window.location.reload();
}

/**
 * The site masthead: the MemeGPT wordmark, then (outside system pages) the
 * Chat/Lore/Make/Arc tabs from 768px up and the account actions, over a
 * red rule. Below 768px the tabs live only in the bottom bar (MobileNav).
 * The active tab is marked with a red underline and aria-current.
 */
export function Masthead(props: Props) {
  const router = useRouter();
  const active = props.variant === "app" ? props.active : null;

  return (
    <header className="shrink-0 bg-background border-b-2 border-brand">
      <div className="flex items-center gap-4 md:gap-10 px-4 md:px-8 min-h-14 md:min-h-[72px]">
        <Link href="/" className="font-display text-2xl md:text-[2rem] leading-none text-foreground py-2.5">
          MemeGPT
        </Link>

        {props.variant !== "system" && (
          <>
            <nav aria-label="MemeGPT" className="hidden md:flex items-center gap-7">
              {APP_TABS.map(({ key, href, label }) => {
                const isActive = key === active;
                return (
                  <Link
                    key={key}
                    href={href}
                    aria-current={isActive ? "page" : undefined}
                    onClick={(e) => navigateWithTransition(router, e, href)}
                    className={`min-h-11 flex items-center text-base font-medium transition-colors
                                duration-[var(--duration-fast)] ${
                                  isActive
                                    ? "text-foreground underline decoration-brand decoration-[3px] underline-offset-[10px]"
                                    : "text-muted-foreground hover:text-foreground"
                                }`}
                  >
                    {label}
                  </Link>
                );
              })}
            </nav>

            <div className="ml-auto flex items-center gap-1 md:gap-3">
              <AuthControl />
              <button
                type="button"
                onClick={handleForgetMe}
                title="Erase your MemeGPT identity, memory, and history from this device"
                className="min-h-11 px-2 text-base text-muted-foreground hover:text-foreground transition-colors
                           duration-[var(--duration-fast)]"
              >
                Forget me
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}
