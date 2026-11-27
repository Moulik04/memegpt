"use client";

interface Props {
  /** Kept for callers; the avatar no longer varies by user. */
  seed?: string;
  /** Email or display name: first character shown, and the a11y label. */
  label: string;
  size?: "sm" | "md";
}

/**
 * The signed-in letter avatar: a black tile with a white Anton initial.
 * Red fills nothing outside Arc, so it no longer picks a red tint per user.
 */
export function Avatar({ label, size = "md" }: Props) {
  const initial = label.trim().charAt(0).toUpperCase() || "?";
  const dims = size === "sm" ? "w-7 h-7 text-sm" : "w-8 h-8 text-base";

  return (
    <div
      role="img"
      aria-label={label}
      className={`font-display ${dims} rounded-[var(--radius)] bg-primary text-primary-foreground
                  flex items-center justify-center shrink-0 leading-none`}
    >
      {initial}
    </div>
  );
}
