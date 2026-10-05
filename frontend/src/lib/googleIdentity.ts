// Google Identity Services — the script behind Google's own "Sign in with
// Google" button. The button hands back a Google ID token in the page, which
// AuthProvider.tsx passes to Supabase (signInWithIdToken), so the whole
// sign-in happens on this site's own origin with no redirect in between.
//
// NEXT_PUBLIC_GOOGLE_CLIENT_ID is the OAuth web client id (public, the same
// one Supabase's Google provider lists). Unset = this button is off and
// AuthControl.tsx falls back to the redirect flow.

export const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

export const googleButtonEnabled = Boolean(GOOGLE_CLIENT_ID);

const SCRIPT_SRC = "https://accounts.google.com/gsi/client";

export interface GoogleCredentialResponse {
  credential?: string;
}

interface GoogleIdConfiguration {
  client_id: string;
  callback: (response: GoogleCredentialResponse) => void;
  nonce: string;
  context: "signin" | "signup" | "use";
  ux_mode: "popup" | "redirect";
  use_fedcm_for_button: boolean;
}

interface GoogleButtonOptions {
  type: "standard" | "icon";
  theme: "outline" | "filled_blue" | "filled_black";
  size: "large" | "medium" | "small";
  text: "signin_with" | "signup_with" | "continue_with" | "signin";
  shape: "rectangular" | "pill";
  logo_alignment: "left" | "center";
  width: number;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: GoogleIdConfiguration) => void;
          renderButton: (parent: HTMLElement, options: GoogleButtonOptions) => void;
        };
      };
    };
  }
}

let scriptPromise: Promise<void> | null = null;

/** Loads Google's script once per page. Rejects if it can't load (offline,
 *  or a content blocker), and lets the next call try again. */
export function loadGoogleIdentity(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (!scriptPromise) {
    scriptPromise = new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = SCRIPT_SRC;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => {
        script.remove();
        scriptPromise = null;
        reject(new Error("Google Identity Services failed to load"));
      };
      document.head.appendChild(script);
    });
  }
  return scriptPromise;
}

/** One sign-in attempt's nonce. Google gets the SHA-256 hash and embeds it
 *  in the ID token; Supabase gets the raw value and checks the two match,
 *  which is what stops a token minted for another page being replayed here. */
export async function createNonce(): Promise<{ raw: string; hashed: string }> {
  const raw = Array.from(crypto.getRandomValues(new Uint8Array(32)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
  const hashed = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  return { raw, hashed };
}
