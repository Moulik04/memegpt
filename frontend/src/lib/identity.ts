// Anonymous identity (Growth Phase C) — a per-browser, no-signup id sent as
// the X-MemeGPT-User header on chat/image/feedback calls. Read fresh at
// every call site rather than cached in a module variable: that's what
// makes "Forget me" trivially correct — the very next request after
// clearing localStorage just generates a fresh id, with zero extra
// invalidation plumbing needed anywhere else.
//
// Safe re: SSR/Next.js — every caller lives inside a "use client" component
// handler or a lib/api.ts function only ever invoked from one, so this
// never runs where `localStorage` doesn't exist.

const STORAGE_KEY = "memegpt_uid";

export function getOrCreateAnonId(): string {
  const existing = window.localStorage.getItem(STORAGE_KEY);
  if (existing) return existing;

  const fresh = crypto.randomUUID();
  window.localStorage.setItem(STORAGE_KEY, fresh);
  return fresh;
}

export function forgetAnonId(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}
