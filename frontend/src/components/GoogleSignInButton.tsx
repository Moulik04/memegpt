"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { GOOGLE_CLIENT_ID, createNonce, loadGoogleIdentity } from "@/lib/googleIdentity";

type Problem = "load" | "signin" | null;

const PROBLEM_COPY: Record<Exclude<Problem, null>, string> = {
  load: "Google sign-in didn't load. A content blocker may be stopping it.",
  signin: "That sign-in didn't go through. Try again.",
};

/**
 * Google's own rendered button (an iframe Google controls — it can't be
 * restyled or swapped for one of ours, the ID-token flow only starts from
 * it). `width` is in px and has to be passed to Google up front, 200-400.
 */
export function GoogleSignInButton({ width }: { width: number }) {
  const { signInWithGoogleIdToken } = useAuth();
  const slot = useRef<HTMLDivElement>(null);
  const [problem, setProblem] = useState<Problem>(null);
  // Bumped after a failed attempt so the button re-initializes with a
  // fresh nonce — a nonce is good for one attempt only.
  const [attempt, setAttempt] = useState(0);

  // Read through a ref so the button isn't torn down and rebuilt every
  // time AuthProvider re-renders with a new function identity.
  const signIn = useRef(signInWithGoogleIdToken);
  useEffect(() => {
    signIn.current = signInWithGoogleIdToken;
  }, [signInWithGoogleIdToken]);

  useEffect(() => {
    let cancelled = false;

    async function mount() {
      let nonce: { raw: string; hashed: string };
      try {
        await loadGoogleIdentity();
        nonce = await createNonce();
      } catch {
        if (!cancelled) setProblem("load");
        return;
      }
      if (cancelled || !slot.current || !window.google) return;

      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        nonce: nonce.hashed,
        context: "signup",
        ux_mode: "popup",
        use_fedcm_for_button: true,
        callback: async (response) => {
          const ok = response.credential
            ? await signIn.current(response.credential, nonce.raw)
            : false;
          // On success AuthControl swaps to the signed-in view and this
          // unmounts, so there's nothing left to update.
          if (!ok && !cancelled) {
            setProblem("signin");
            setAttempt((n) => n + 1);
          }
        },
      });
      slot.current.replaceChildren();
      window.google.accounts.id.renderButton(slot.current, {
        type: "standard",
        theme: "filled_black",
        size: "large",
        text: "continue_with",
        shape: "rectangular",
        logo_alignment: "left",
        width,
      });
    }

    mount();
    return () => {
      cancelled = true;
    };
  }, [attempt, width]);

  return (
    <div className="flex flex-col gap-2">
      {/* scheme-light: Google's iframe paints an opaque backdrop behind the
          button when it inherits a dark color-scheme. h-10 holds the large
          button's height so the popover doesn't jump when it arrives. */}
      <div ref={slot} className="h-10 scheme-light" />
      {problem && (
        <p role="alert" className="text-[11px] text-muted-foreground">
          {PROBLEM_COPY[problem]}
        </p>
      )}
    </div>
  );
}
