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
import { Button } from "@/components/ui/button";
import { GoogleSignInButton } from "@/components/GoogleSignInButton";
import { googleButtonEnabled } from "@/lib/googleIdentity";

// The popover's inner width: w-64 (256px) minus PopoverContent's p-2.5 on
// each side. Google's button needs its width in px up front, and it won't
// render narrower than its label needs (209px for "Continue with Google"
// in English, more in some languages), so leave it room.
const GOOGLE_BUTTON_WIDTH = 236;

function truncateEmail(email: string): string {
  return email.length > 22 ? `${email.slice(0, 19)}…` : email;
}

/**
 * Renders null when Supabase Auth isn't configured (empty env vars) —
 * signed-out visitors and every existing test/screenshot of the app are
 * completely unaffected. Slots into ModeTabs.tsx's right-hand chrome
 * alongside "Forget me", and into LandingPage.tsx.
 */
export function AuthControl() {
  const { user, loading, signInWithGoogle, signOut } = useAuth();
  const [open, setOpen] = useState(false);

  if (!authEnabled || loading) return null;

  if (user) {
    return (
      <div className="flex items-center gap-2">
        <Avatar seed={user.id} label={user.email ?? "Signed in"} size="sm" />
        <span className="text-[11px] text-gray-500" title={user.email ?? undefined}>
          {user.email ? truncateEmail(user.email) : "Signed in"}
        </span>
        <button
          type="button"
          onClick={() => signOut()}
          className="text-[11px] text-gray-600 hover:text-gray-400 transition-colors"
        >
          Sign out
        </button>
      </div>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="text-[11px] text-gray-600 hover:text-gray-400 transition-colors"
        >
          Sign in
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" collisionPadding={8} className="w-64">
        {googleButtonEnabled ? (
          <GoogleSignInButton width={GOOGLE_BUTTON_WIDTH} />
        ) : (
          <Button
            type="button"
            variant="secondary"
            className="w-full"
            onClick={() => {
              setOpen(false);
              signInWithGoogle();
            }}
          >
            Continue with Google
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}
