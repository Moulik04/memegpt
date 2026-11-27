/**
 * Motion timings for motion/react, mirroring the tokens in globals.css
 * (--ease-settle, --duration-fast, --duration-settle, --duration-arrive)
 * and the handoff's motion table, section 6.
 */
export const EASE_SETTLE = [0.16, 1, 0.3, 1] as const;

/** Photos entering a composer. */
export const FAST_SETTLE = { duration: 0.15, ease: EASE_SETTLE };
/** Dialogs, status lines, expanding text. */
export const FAST_OUT = { duration: 0.15, ease: "easeOut" } as const;
/** Swaps, Lore's rows, Arc's frames. */
export const SETTLE = { duration: 0.24, ease: EASE_SETTLE };
/** A new Chat answer taking the lead. */
export const ARRIVE = { duration: 0.32, ease: EASE_SETTLE };
/** Reduced motion: the same state change, at once. */
export const INSTANT = { duration: 0 } as const;
