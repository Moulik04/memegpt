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
  signInWithEmail: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const noop = async () => {};

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  session: null,
  loading: false,
  signInWithGoogle: noop,
  signInWithEmail: noop,
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

  async function signInWithGoogle() {
    if (!supabase) return;
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
  }

  async function signInWithEmail(email: string) {
    if (!supabase) return;
    await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
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
        signInWithEmail,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
