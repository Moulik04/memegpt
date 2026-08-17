"use client";

import { useEffect, useRef, useState } from "react";

const SCRAMBLE_CHARS = "!<>-_\\/[]{}—=+*^?#________";

/**
 * Cycles random characters per-position before settling on the real text —
 * reads as "resolving," not decorative. Used for plain-text replies (the
 * graceful-degrade path when a meme can't be made), which are the one
 * place real generated text lands in the UI outside a baked-in meme image.
 * Respects prefers-reduced-motion by just rendering the final text.
 */
export function DecryptedText({ text, className }: { text: string; className?: string }) {
  const [display, setDisplay] = useState(text);
  const frame = useRef(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(text);
      return;
    }

    let cancelled = false;
    const TOTAL_FRAMES = 12;
    frame.current = 0;

    function tick() {
      if (cancelled) return;
      frame.current += 1;
      const revealCount = Math.floor((frame.current / TOTAL_FRAMES) * text.length);
      const next = text
        .split("")
        .map((ch, i) => {
          if (ch === " " || ch === "\n") return ch;
          if (i < revealCount) return ch;
          return SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)];
        })
        .join("");
      setDisplay(next);
      if (frame.current < TOTAL_FRAMES) {
        setTimeout(tick, 28);
      } else {
        setDisplay(text);
      }
    }
    tick();

    return () => {
      cancelled = true;
    };
  }, [text]);

  return <span className={className}>{display}</span>;
}
