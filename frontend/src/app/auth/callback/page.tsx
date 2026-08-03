"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";

/**
 * Redirect target for both Google OAuth and email magic-link sign-in
 * (AuthProvider.tsx's signInWithGoogle/signInWithEmail both point here).
 * supabase-js's browser client defaults to the PKCE flow, which lands here
 * with a `?code=` query param that must be exchanged for a session before
 * any other page can see the user as signed in.
 */
export default function AuthCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    async function finish() {
      const code = new URLSearchParams(window.location.search).get("code");
      if (supabase && code) {
        await supabase.auth.exchangeCodeForSession(code);
      }
      router.replace("/chat");
    }
    finish();
  }, [router]);

  return (
    <div className="flex h-dvh items-center justify-center bg-gray-950 text-gray-400 text-sm">
      Signing you in…
    </div>
  );
}
