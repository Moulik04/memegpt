"use client";

import { useState } from "react";
import { authEnabled } from "@/lib/supabaseClient";
import { useAuth } from "@/hooks/useAuth";
import { Avatar } from "@/components/Avatar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { GoogleSignInButton } from "@/components/GoogleSignInButton";
import { googleButtonEnabled } from "@/lib/googleIdentity";

// The popover's inner width: w-64 (256px) minus PopoverContent's p-2.5 on
// each side. Google's button needs its width in px up front, and it won't
// render narrower than its label needs (209px for "Continue with Google"
// in English, more in some languages), so leave it room.
const GOOGLE_BUTTON_WIDTH = 236;

/** The copy deck, section 7.6. */
const SIGN_IN_INTRO = "Every part works without an account. Signing in only adds saved chat history across devices.";

const MENU_ITEM =
  "w-full min-h-11 px-2 text-left text-base font-medium text-foreground hover:bg-muted " +
  "transition-colors duration-[var(--duration-fast)]";

/**
 * Renders null when Supabase Auth isn't configured (empty env vars) —
 * signed-out visitors and every existing test/screenshot of the app are
 * completely unaffected. Slots into Masthead.tsx's account actions,
 * beside "Forget me". Signed in, the letter avatar opens the account menu:
 * the signed-in email, History where the page has it, and Sign out.
 */
export function AuthControl({
  onHistory,
  signInOpen,
  onSignInOpenChange,
}: {
  onHistory?: () => void;
  /** The sign-in popover's state, held by the masthead so Forget me can
   * open it after a sign-in the server couldn't confirm. */
  signInOpen: boolean;
  onSignInOpenChange: (open: boolean) => void;
}) {
  const { user, loading, signInWithGoogle, signOut } = useAuth();
  const open = signInOpen;
  const setOpen = onSignInOpenChange;
  const [menuOpen, setMenuOpen] = useState(false);

  if (!authEnabled || loading) return null;

  if (user) {
    return (
      <Popover open={menuOpen} onOpenChange={setMenuOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label="Account"
            className="min-h-11 min-w-11 flex items-center justify-center"
          >
            <Avatar seed={user.id} label={user.email ?? "Signed in"} size="sm" />
          </button>
        </PopoverTrigger>
        <PopoverContent aria-label="Account" align="end" collisionPadding={8} className="w-64 p-2 flex flex-col gap-1">
          <p className="px-2 py-2 text-sm text-muted-foreground break-all">{user.email ?? "Signed in"}</p>
          {onHistory && (
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                onHistory();
              }}
              className={MENU_ITEM}
            >
              History
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              setMenuOpen(false);
              signOut();
            }}
            className={MENU_ITEM}
          >
            Sign out
          </button>
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="min-h-11 px-2 text-base font-medium text-foreground hover:text-muted-foreground transition-colors"
        >
          Sign in
        </button>
      </PopoverTrigger>
      <PopoverContent aria-label="Sign in" align="end" collisionPadding={8} className="w-64 flex flex-col gap-3">
        <p className="text-base text-foreground">{SIGN_IN_INTRO}</p>
        {googleButtonEnabled ? (
          <GoogleSignInButton width={GOOGLE_BUTTON_WIDTH} />
        ) : (
          <button
            type="button"
            className="w-full min-h-11 px-4 rounded-sm bg-primary text-primary-foreground text-base font-semibold
                       hover:bg-primary/85 transition-colors duration-[var(--duration-fast)]"
            onClick={() => {
              setOpen(false);
              signInWithGoogle();
            }}
          >
            Continue with Google
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}
