"use client";

import { useEffect, useRef, useState } from "react";
import { pickBudgetMeme } from "@/lib/budgetMemes";

/**
 * The "daily AI budget used up" reply: one of the ready-made memes, in the
 * shared meme frame, with the notice under it. No action row: the meme has
 * nothing to do with the request and has no share page. The text renders
 * whether or not the image loads, and is the image's alt text as well.
 *
 * The meme is picked after mount, not during render, and once per notice:
 * a pick writes the "last shown" marker, and both a render and an effect
 * can run more than once for the same notice. Picking twice would show the
 * second pick, which is only guaranteed to differ from the first, not from
 * the meme this visitor actually saw last time.
 */
export default function BudgetNotice({
  message,
  maxHeightClassName = "max-h-80",
}: {
  message: string;
  maxHeightClassName?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const picked = useRef<string | null>(null);

  useEffect(() => {
    if (!picked.current) picked.current = pickBudgetMeme();
    setSrc(picked.current);
  }, []);

  return (
    <div className="flex flex-col items-start gap-3" role="status">
      {src && (
        <figure className="max-w-full bg-meme-mat border border-meme-edge p-2 md:p-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- natural size */}
          <img
            src={src}
            alt={message}
            className={`block w-auto h-auto max-w-full ${maxHeightClassName} border border-meme-edge`}
          />
        </figure>
      )}
      <p className="text-base text-foreground border-l-2 border-brand pl-3 max-w-prose">{message}</p>
    </div>
  );
}
