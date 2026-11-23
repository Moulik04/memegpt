"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Download, Share, ThumbsDown, ThumbsUp } from "lucide-react";
import { memeImageUrl } from "@/lib/api";

interface Props {
  url: string;
  /** Builds the /m/{id} share link when there's nowhere to send the file. */
  memeId?: string;
  /** Omit where a meme takes no rating, as in Make. */
  onFeedback?: (rating: "up" | "down") => void;
  /** A rating already given, when the caller keeps track across remounts. */
  rating?: "up" | "down";
  /** An action shown first, such as Lore's Another take. */
  lead?: ReactNode;
  /** Keep the lead in the row on a phone too. Only for a short row, as in
   * Make, where it sits beside Share and Download with no ratings. */
  leadInline?: boolean;
}

type ShareNote = "copied" | "failed" | null;

export const MEME_ACTION =
  "min-h-11 min-w-11 px-2 inline-flex items-center justify-center gap-1.5 text-base font-medium " +
  "text-muted-foreground hover:text-foreground transition-colors duration-[var(--duration-fast)] " +
  "disabled:cursor-not-allowed";

/**
 * A meme's quiet action row: Thumbs up and Thumbs down (only where the meme
 * takes a rating), Share and Download. Unboxed, small icons, 44px targets.
 * A rating is given once and stays marked.
 */
export function MemeActions({ url, memeId, onFeedback, rating: given, lead, leadInline = false }: Props) {
  const [rating, setRating] = useState<"up" | "down" | null>(given ?? null);
  const [note, setNote] = useState<ShareNote>(null);
  const [downloading, setDownloading] = useState(false);
  const fileRef = useRef<File | null>(null);
  const noteTimer = useRef<ReturnType<typeof setTimeout>>();

  const fullUrl = url.startsWith("http") ? url : memeImageUrl(url);

  // Fetched ahead of time: mobile browsers only open the share sheet when
  // navigator.share() runs straight from the tap, with no await before it.
  useEffect(() => {
    let cancelled = false;
    fetch(fullUrl)
      .then((res) => res.blob())
      .then((blob) => {
        if (!cancelled) fileRef.current = new File([blob], "meme.png", { type: blob.type || "image/png" });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [fullUrl]);

  useEffect(() => () => clearTimeout(noteTimer.current), []);

  function showNote(next: ShareNote) {
    setNote(next);
    clearTimeout(noteTimer.current);
    noteTimer.current = setTimeout(() => setNote(null), 3000);
  }

  function rate(next: "up" | "down") {
    if (rating || !onFeedback) return;
    setRating(next);
    onFeedback(next);
  }

  function handleShare() {
    const file = fileRef.current;
    if (file && navigator.canShare?.({ files: [file] })) {
      navigator.share({ files: [file], title: "MemeGPT" }).catch(() => {});
      return;
    }
    const link = memeId ? `${window.location.origin}/m/${memeId}` : fullUrl;
    if (navigator.share) {
      navigator.share({ url: link, title: "MemeGPT" }).catch(() => {});
      return;
    }
    // No clipboard at all outside a secure context.
    if (!navigator.clipboard) {
      showNote("failed");
      return;
    }
    navigator.clipboard
      .writeText(link)
      .then(() => showNote("copied"))
      .catch(() => showNote("failed"));
  }

  async function handleDownload() {
    if (downloading) return;
    setDownloading(true);
    try {
      const blob: Blob = fileRef.current ?? (await (await fetch(fullUrl)).blob());
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = "meme.png";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
    } catch {
      window.open(fullUrl, "_blank");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-1 -ml-2">
      {/* On a phone the lead action takes its own line, so the rest of
          the row never wraps one action onto a line by itself. */}
      {lead && <div className={`${leadInline ? "" : "basis-full sm:basis-auto "}flex`}>{lead}</div>}
      {onFeedback && (
        <>
          {(["up", "down"] as const).map((value) => {
            const Icon = value === "up" ? ThumbsUp : ThumbsDown;
            const chosen = rating === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => rate(value)}
                aria-label={value === "up" ? "Thumbs up" : "Thumbs down"}
                aria-pressed={chosen}
                disabled={rating !== null && !chosen}
                className={`${MEME_ACTION} ${chosen ? "text-foreground" : ""} ${
                  rating !== null && !chosen ? "opacity-40" : ""
                }`}
              >
                <Icon size={18} strokeWidth={2} fill={chosen ? "currentColor" : "none"} aria-hidden="true" />
              </button>
            );
          })}
        </>
      )}
      <button type="button" onClick={handleShare} className={MEME_ACTION}>
        <Share size={16} strokeWidth={2} aria-hidden="true" />
        Share
      </button>
      <button type="button" onClick={handleDownload} aria-busy={downloading} className={MEME_ACTION}>
        <Download size={16} strokeWidth={2} aria-hidden="true" />
        Download
      </button>
      <span role="status" className="text-sm text-muted-foreground px-2">
        {note === "copied" ? "Link copied" : note === "failed" ? "Couldn't share. Try Download." : ""}
      </span>
    </div>
  );
}
