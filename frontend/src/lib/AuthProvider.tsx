"use client";

import { createContext, useEffect, useState } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { authEnabled, supabase } from "@/lib/supabaseClient";
import { linkAnonAccount } from "@/lib/api";

export interface AuthContextValue {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signInWithGoogle: () => Promise<void>;
  /** Resolves true once Supabase has accepted Google's ID token. */
  signInWithGoogleIdToken: (token: string, nonce: string) => Promise<boolean>;
  signOut: () => Promise<void>;
}

const noop = async () => {};

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  session: null,
  loading: false,
  signInWithGoogle: noop,
  signInWithGoogleIdToken: async () => false,
  signOut: noop,
});

/**
 * Wraps the whole app (see app/layout.tsx). A no-op passthrough when
 * !authEnabled — every consumer sees user/session as permanently null
 * rather than needing its own "is auth even configured" branch.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(authEnabled);

  useEffect(() => {
    if (!supabase) return;

    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((event, newSession) => {
      setSession(newSession);
      // Growth Phase H, Stage 2 — link this browser's anonymous history to
      // the account exactly once per real sign-in (not on every
      // TOKEN_REFRESHED firing for an already-signed-in session). Fire-
      // and-forget: a failure here just means personalization stays
      // anon-only for now, never worth blocking the sign-in UI over.
      if (event === "SIGNED_IN") {
        linkAnonAccount().catch(() => {});
      }
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  // Redirect flow — only reached when NEXT_PUBLIC_GOOGLE_CLIENT_ID is unset
  // (see AuthControl.tsx). GoogleSignInButton's ID-token flow below is the
  // real path.
  async function signInWithGoogle() {
    if (!supabase) return;
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
  }

  // `token` is the ID token Google's button returned in the page, `nonce`
  // the raw value whose hash went to Google (lib/googleIdentity.ts). No
  // redirect, no /auth/callback — onAuthStateChange above fires SIGNED_IN
  // exactly as it does for the redirect flow.
  async function signInWithGoogleIdToken(token: string, nonce: string) {
    if (!supabase) return false;
    const { error } = await supabase.auth.signInWithIdToken({
      provider: "google",
      token,
      nonce,
    });
    return !error;
  }

  async function signOut() {
    if (!supabase) return;
    await supabase.auth.signOut();
  }

  return (
    <AuthContext.Provider
      value={{
        user: session?.user ?? null,
        session,
        loading,
        signInWithGoogle,
        signInWithGoogleIdToken,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
