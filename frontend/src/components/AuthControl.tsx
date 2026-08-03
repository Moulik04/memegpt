"use client";

import { useState } from "react";
import { authEnabled } from "@/lib/supabaseClient";
import { useAuth } from "@/hooks/useAuth";

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
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] text-gray-600 hover:text-gray-400 transition-colors"
      >
        Sign in
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-56 rounded-xl border border-gray-800 bg-[#0c0c14] p-3 shadow-xl z-50 flex flex-col gap-2">
          <p className="text-[11px] text-gray-500 leading-snug">
            Signed-in chat history saves what you type so you can revisit it
            later. Anonymous use never stores your messages.
          </p>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              signInWithGoogle();
            }}
            className="text-xs font-medium rounded-lg px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-100 transition-colors"
          >
            Continue with Google
          </button>
          <div className="flex items-center gap-2 text-[10px] text-gray-600">
            <div className="flex-1 h-px bg-gray-800" />
            or
            <div className="flex-1 h-px bg-gray-800" />
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
                className="text-xs rounded-lg px-3 py-2 bg-[#13131e] border border-gray-800 text-gray-100 placeholder:text-gray-600 focus:outline-none focus:border-brand-600"
              />
              <button
                type="submit"
                className="text-xs font-medium rounded-lg px-3 py-2 bg-brand-600 hover:bg-brand-500 text-white transition-colors"
              >
                Send magic link
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
