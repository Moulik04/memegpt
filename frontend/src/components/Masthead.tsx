"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthControl } from "@/components/AuthControl";
import { ForgetMeDialog } from "@/components/ForgetMeDialog";
import { navigateWithTransition } from "@/lib/viewTransition";
import { APP_TABS, type AppTab } from "@/lib/appTabs";
import { useAuth } from "@/hooks/useAuth";
import { useConversation } from "@/lib/ConversationContext";

type Props =
  /** Chat, Lore, Make, Arc: one tab is active. `history` adds the History
   * button for signed-in visitors, on the surfaces with saved chats. */
  | { variant: "app"; active: AppTab; history?: boolean }
  /** The landing page: tabs shown, none active. */
  | { variant: "landing" }
  /** Shared meme, privacy, 404, error, sign-in redirect: wordmark only.
   * `unlinked` drops the wordmark's link, for the maintenance page. */
  | { variant: "system"; unlinked?: boolean };

/**
 * The site masthead: the MemeGPT wordmark, then (outside system pages) the
 * Chat/Lore/Make/Arc tabs from 768px up and the account actions, over a
 * red rule. Below 768px the tabs live only in the bottom bar (MobileNav).
 * The active tab is marked with a red underline and aria-current.
 */
export function Masthead(props: Props) {
  const router = useRouter();
  const active = props.variant === "app" ? props.active : null;
  const { user } = useAuth();
  const { setHistoryOpen } = useConversation();
  const showHistory = props.variant === "app" && props.history && !!user;
  const [forgetOpen, setForgetOpen] = useState(false);
  const [signInOpen, setSignInOpen] = useState(false);
  const unlinked = props.variant === "system" && props.unlinked;
  const wordmark = "font-display text-2xl md:text-[2rem] leading-none text-foreground py-2.5";

  return (
    <header className="shrink-0 bg-background border-b-2 border-brand">
      <div className="flex items-center gap-4 md:gap-10 px-4 md:px-8 min-h-14 md:min-h-[72px]">
        {unlinked ? (
          <span className={wordmark}>MemeGPT</span>
        ) : (
          <Link href="/" className={wordmark}>
            MemeGPT
          </Link>
        )}

        {props.variant !== "system" && (
          <>
            <nav aria-label="MemeGPT" className="hidden md:flex items-center gap-4">
              {APP_TABS.map(({ key, href, label }) => {
                const isActive = key === active;
                return (
                  <Link
                    key={key}
                    href={href}
                    aria-current={isActive ? "page" : undefined}
                    onClick={(e) => navigateWithTransition(router, e, href)}
                    className={`min-h-11 min-w-11 px-1.5 flex items-center justify-center text-base font-medium transition-colors
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
              {/* On a phone, History is in the account menu only. */}
              {showHistory && (
                <button
                  type="button"
                  onClick={() => setHistoryOpen(true)}
                  aria-haspopup="dialog"
                  className="hidden md:inline-flex items-center min-h-11 px-2 text-base font-medium text-foreground
                             transition-colors duration-[var(--duration-fast)]"
                >
                  History
                </button>
              )}
              <AuthControl
                onHistory={showHistory ? () => setHistoryOpen(true) : undefined}
                signInOpen={signInOpen}
                onSignInOpenChange={setSignInOpen}
              />
              <ForgetMeDialog
                open={forgetOpen}
                onOpenChange={setForgetOpen}
                onSignIn={() => setSignInOpen(true)}
                trigger={
                  <button
                    type="button"
                    className="min-h-11 px-2 text-base text-muted-foreground hover:text-foreground transition-colors
                               duration-[var(--duration-fast)]"
                  >
                    Forget me
                  </button>
                }
              />
            </div>
          </>
        )}
      </div>
    </header>
  );
}
