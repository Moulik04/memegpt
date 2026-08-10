"use client";

import { MemeDisplay } from "./MemeDisplay";
import { FeedbackButtons } from "./FeedbackButtons";
import { ShareButtons } from "./ShareButtons";

interface Props {
  url: string;
  alt?: string;
  /** Omit for contexts with no feedback concept (e.g. the public share page). */
  onFeedback?: (rating: "up" | "down") => void;
  /** ShareButtons' large/primary mode — the public share page. */
  large?: boolean;
}

/**
 * The single-meme card: image + actions row, in its own bordered surface.
 * Covers the two contexts that actually share this exact shape (Chat's
 * single-meme bubble, Lore's flat-feed entries) plus the public share page
 * in `large` mode. Chat's multi-meme carousel keeps its own structure —
 * one shared action bar for the whole scroll strip, not one per image —
 * genuinely different enough not to force through this same component.
 */
export function MemeCard({ url, alt, onFeedback, large }: Props) {
  return (
    <div className="rounded-2xl bg-card border border-border p-3 shadow-lg">
      <MemeDisplay url={url} alt={alt} />
      <div className="flex items-center justify-between mt-2">
        <ShareButtons memeUrl={url} large={large} />
        {onFeedback && <FeedbackButtons onFeedback={onFeedback} />}
      </div>
    </div>
  );
}
