"use client";

import { useEffect, useRef, useState } from "react";
import { MemeDisplay } from "./MemeDisplay";
import { FeedbackButtons } from "./FeedbackButtons";
import { ShareButtons } from "./ShareButtons";
import { templateLabel } from "@/lib/utils";

// Module-level, not component state — registered once for the whole app
// (not per-card) so it already has a real reading by the time any card
// mounts, rather than starting blank and needing its own first movement
// to become useful. See the comment on flipped's mouseenter handler below
// for why this exists at all.
let lastKnownMouse = { x: -1, y: -1 };
if (typeof window !== "undefined") {
  window.addEventListener("mousemove", (e) => {
    lastKnownMouse = { x: e.clientX, y: e.clientY };
  });
}

interface Props {
  url: string;
  alt?: string;
  /** Omit for contexts with no feedback concept (e.g. the public share page). */
  onFeedback?: (rating: "up" | "down") => void;
  /** ShareButtons' large/primary mode — the public share page. */
  large?: boolean;
  /** When present, hovering the image flips it to reveal which template
   * was used. Omit where it's not available (e.g. Arc's share screen). */
  templateId?: string;
}

/**
 * The single-meme card: image + actions row, in its own bordered surface.
 * Used by Lore's flat-feed entries, Make's generate result, Arc's share
 * screen, and the public share page (`large` mode). Chat's single-meme
 * bubble uses it too, but Chat's multi-meme carousel keeps its own
 * structure — one shared action bar for the whole scroll strip, not one
 * per image — genuinely different enough not to force through this same
 * component.
 */
export function MemeCard({ url, alt, onFeedback, large, templateId }: Props) {
  // A card can land right under a cursor that's just resting there from
  // whatever action produced it (e.g. Make's "Generate" button sits where
  // the result card then renders). Two things confirmed live, both
  // insufficient alone: CSS :hover re-evaluates the instant pointer-events
  // re-enables regardless of movement, AND Chromium fires a real
  // onMouseEnter when the DOM mutates under a stationary cursor (a new
  // element appearing where an old one was reads as the pointer "entering"
  // it, even with zero physical movement) — so neither a plain group-hover
  // class nor a plain onMouseEnter handler is enough on its own. The fix:
  // record where the cursor already was the instant this card mounted,
  // and only treat a mouseenter as real if the cursor has since moved a
  // real distance from that point — a mouseenter fired by a DOM mutation
  // under a stationary cursor reports the exact same coordinates.
  const [flipped, setFlipped] = useState(false);
  const mountMouse = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    mountMouse.current = { ...lastKnownMouse };
  }, []);

  function handleMouseEnter() {
    const at = mountMouse.current;
    if (at) {
      const dx = Math.abs(lastKnownMouse.x - at.x);
      const dy = Math.abs(lastKnownMouse.y - at.y);
      if (dx < 4 && dy < 4) return; // same spot — not a real hover
    }
    setFlipped(true);
  }

  return (
    <div
      className="rounded-2xl bg-card border border-border p-3 shadow-lg
                 hover:border-gray-700 hover:shadow-xl hover:-translate-y-0.5
                 transition-all duration-[var(--duration-settle)]"
    >
      {templateId ? (
        <div
          className="[perspective:1000px]"
          onMouseEnter={handleMouseEnter}
          onMouseLeave={() => setFlipped(false)}
        >
          <div
            className={`relative transition-transform duration-500 [transform-style:preserve-3d] ${
              flipped ? "[transform:rotateY(180deg)]" : ""
            }`}
          >
            <div className="[backface-visibility:hidden]">
              <MemeDisplay url={url} alt={alt} />
            </div>
            <div
              className="absolute inset-0 mt-2 rounded-xl border border-gray-700/60 bg-ink-1
                         flex items-center justify-center px-4 text-center
                         [backface-visibility:hidden] [transform:rotateY(180deg)]"
            >
              <span className="caption caption-mark text-lg">{templateLabel(templateId)}</span>
            </div>
          </div>
        </div>
      ) : (
        <MemeDisplay url={url} alt={alt} />
      )}
      <div className="flex items-center justify-between mt-2">
        <ShareButtons memeUrl={url} large={large} />
        {onFeedback && <FeedbackButtons onFeedback={onFeedback} />}
      </div>
    </div>
  );
}
