"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import { Masthead } from "@/components/Masthead";

/**
 * Redirect target for the Google OAuth redirect flow (AuthProvider.tsx's
 * signInWithGoogle). Google's own button (GoogleSignInButton.tsx) never
 * comes through here. supabase-js's browser client defaults to the PKCE
 * flow, which lands here with a `?code=` query param that must be
 * exchanged for a session before any other page can see the user as
 * signed in.
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
    <div className="flex flex-col h-dvh bg-background">
      <Masthead variant="system" />
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-base">
        Signing you in…
      </div>
    </div>
  );
}
