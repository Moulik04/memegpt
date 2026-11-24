"use client";

import { useRef, useState } from "react";
import { ApiError, ERASE_FAILED, forgetMe } from "@/lib/api";
import { forgetAnonId } from "@/lib/identity";
import { useAuth } from "@/hooks/useAuth";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

/** The copy deck, section 7.6. */
const TITLE = "Forget me";
const ERASING = "Erasing…";
const SIGNED_OUT_LEAD = "This erases your memes, ratings and remembered lore from this browser.";
const SIGNED_OUT_REST =
  "Share links to those memes stop working. Your Arc starts over. This can't be undone. Chats saved to an account are only erased while you're signed in to it.";
const SIGNED_IN_LEAD = "This erases your chats, memes, ratings and remembered lore.";
const SIGNED_IN_REST =
  "Share links to those memes stop working. Your Arc starts over. This can't be undone. Your account itself stays. To delete it, email support.memegpt@gmail.com.";
const SIGN_IN_NOT_CONFIRMED = "MemeGPT couldn't confirm your sign-in, so nothing was erased. Sign in again and retry.";

type Phase = "confirm" | "erasing" | "failed" | "signin";

const MAIN_BUTTON =
  "min-h-11 px-5 rounded-sm bg-primary text-primary-foreground text-base font-semibold hover:bg-primary/85 " +
  "disabled:opacity-60 transition-colors duration-[var(--duration-fast)]";
const SECOND_BUTTON =
  "min-h-11 px-5 rounded-sm border border-input text-base font-medium text-foreground hover:bg-muted " +
  "disabled:opacity-40 transition-colors duration-[var(--duration-fast)]";

/**
 * Forget me's confirmation. Failures stay inside the dialog: an erase that
 * failed offers Try again, and a sign-in the server couldn't confirm offers
 * Sign in. It never says data is still there, since images can be gone
 * before the rest fails.
 */
export function ForgetMeDialog({
  open,
  onOpenChange,
  onSignIn,
  trigger,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Opens the sign-in popover once the stale session is cleared. */
  onSignIn: () => void;
  /** The header's Forget me link. Focus returns to it on close. */
  trigger: React.ReactElement;
}) {
  const { user, signOut } = useAuth();
  const [phase, setPhase] = useState<Phase>("confirm");
  const [failure, setFailure] = useState(ERASE_FAILED);
  // Set when Sign in closes the dialog, so focus goes to the sign-in
  // popover rather than back to the Forget me link.
  const toSignIn = useRef(false);
  const erasing = phase === "erasing";

  function setOpen(next: boolean) {
    if (erasing) return;
    if (!next) {
      setPhase("confirm");
      setFailure(ERASE_FAILED);
    }
    onOpenChange(next);
  }

  async function erase() {
    setPhase("erasing");
    try {
      await forgetMe();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setPhase("signin");
        return;
      }
      setFailure(err instanceof ApiError && err.reason === "busy" ? err.message : ERASE_FAILED);
      setPhase("failed");
      return;
    }
    forgetAnonId();
    window.location.reload();
  }

  async function signInAgain() {
    toSignIn.current = true;
    setPhase("confirm");
    onOpenChange(false);
    await signOut();
    onSignIn();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        showCloseButton={false}
        onCloseAutoFocus={(e) => {
          if (toSignIn.current) {
            e.preventDefault();
            toSignIn.current = false;
          }
        }}
        className="rounded-sm sm:max-w-md p-5 gap-4 ring-0 border border-foreground bg-background"
      >
        <DialogTitle className="font-display text-3xl leading-none text-foreground">{TITLE}</DialogTitle>
        <DialogDescription asChild className="text-base text-foreground flex flex-col gap-2">
          <div>
            <p className="font-semibold">{user ? SIGNED_IN_LEAD : SIGNED_OUT_LEAD}</p>
            <p>{user ? SIGNED_IN_REST : SIGNED_OUT_REST}</p>
          </div>
        </DialogDescription>

        {(phase === "failed" || phase === "signin") && (
          <p role="alert" className="text-base text-foreground border-l-2 border-brand pl-3">
            {phase === "signin" ? SIGN_IN_NOT_CONFIRMED : failure}
          </p>
        )}
        {erasing && (
          <p role="status" className="sr-only">
            {ERASING}
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={() => setOpen(false)} disabled={erasing} className={SECOND_BUTTON}>
            Cancel
          </button>
          {phase === "signin" ? (
            <button type="button" onClick={signInAgain} className={MAIN_BUTTON}>
              Sign in
            </button>
          ) : (
            <button type="button" onClick={erase} disabled={erasing} className={MAIN_BUTTON}>
              {erasing ? ERASING : phase === "failed" ? "Try again" : TITLE}
            </button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
