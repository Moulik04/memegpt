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
  const { user, loading, signInWithGoogle, signInWithEmail, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

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
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSent(false);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className="text-[11px] text-gray-600 hover:text-gray-400 transition-colors"
        >
          Sign in
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56">
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
        <div className="flex items-center gap-2 text-[10px] text-gray-600">
          <div className="flex-1 h-px bg-border" />
          or
          <div className="flex-1 h-px bg-border" />
        </div>
        {sent ? (
          <p className="text-[11px] text-gray-500">Check your email for a sign-in link.</p>
        ) : (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!email.trim()) return;
              await signInWithEmail(email.trim());
              setSent(true);
            }}
            className="flex flex-col gap-2"
          >
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="text-xs rounded-lg px-3 py-2 bg-card border border-border text-gray-100 placeholder:text-gray-600 focus:outline-none focus:border-accent"
            />
            <Button type="submit" className="w-full">
              Send magic link
            </Button>
          </form>
        )}
      </PopoverContent>
    </Popover>
  );
}
