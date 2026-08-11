"use client";

import { useEffect, useState } from "react";

// Same deterministic-pick algorithm as backend/arc/copy.py's
// _stable_index(): SHA-256 the key, read the full digest as one big
// integer, mod by the option count. Not Math.random() (different every
// render) and not a JS string-hash shortcut (would drift from the
// backend's actual algorithm) — BigInt is what makes reproducing
// int(hexdigest, 16) % n exactly possible in JS, since a 256-bit digest
// doesn't fit in a regular Number.
async function stableIndex(key: string, n: number): Promise<number> {
  const bytes = new TextEncoder().encode(key);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return Number(BigInt(`0x${hex}`) % BigInt(n));
}

// Variants of the one accent hue (never a second color — the monochrome
// rule applies here too), mixed toward paper (not ink) for spread. Mixing
// toward ink/black was the original design here, but this avatar always
// sits on the near-black header/sidebar background (--ink-0/--ink-1) — a
// darkened accent blends straight into it. Mixing toward paper instead
// keeps every stop a visibly lighter, warmer tint than the background at
// any hash value, and the one non-filled variant uses a fully-opaque
// (not /50) ring so it doesn't rely on fill contrast at all.
const PALETTE = [
  "bg-accent",
  "bg-[color-mix(in_oklch,var(--accent-color)_80%,var(--paper))]",
  "bg-[color-mix(in_oklch,var(--accent-color)_60%,var(--paper))]",
  "bg-[color-mix(in_oklch,var(--accent-color)_45%,var(--paper))]",
  "bg-ink-2 border-2 border-accent",
];

interface Props {
  /** Stable per-user key (Supabase user id) — the color source. */
  seed: string;
  /** Email or display name — first character shown, and the a11y label. */
  label: string;
  size?: "sm" | "md";
}

export function Avatar({ seed, label, size = "md" }: Props) {
  // crypto.subtle.digest is async — no synchronous equivalent exists in
  // the Web Crypto API. Renders a neutral placeholder for one paint, then
  // the real color resolves. One-time cost per mount, not per navigation;
  // no SSR/hydration-mismatch risk since `seed` is never available during
  // server rendering anyway (no user during SSR).
  const [colorClass, setColorClass] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    stableIndex(seed, PALETTE.length).then((i) => {
      if (!cancelled) setColorClass(PALETTE[i]);
    });
    return () => {
      cancelled = true;
    };
  }, [seed]);

  const initial = label.trim().charAt(0).toUpperCase() || "?";
  const dims = size === "sm" ? "w-6 h-6 text-[10px]" : "w-8 h-8 text-xs";

  return (
    <div
      role="img"
      aria-label={label}
      className={`caption ${dims} rounded-full flex items-center justify-center shrink-0 transition-colors ${
        colorClass ?? "bg-ink-2"
      }`}
    >
      {initial}
    </div>
  );
}
