"use client";

import { useEffect, useRef, useState } from "react";
import { pickBudgetMeme } from "@/lib/budgetMemes";

/**
 * The "daily AI budget used up" reply: one of the pre-made memes, with the
 * notice as text beside it. The text is rendered whether or not the image
 * loads, and is the image's alt text as well.
 *
 * The meme is picked after mount, not during render, and once per notice:
 * a pick writes the "last shown" marker, and both a render and an effect
 * can run more than once for the same notice. Picking twice would show the
 * second pick, which is only guaranteed to differ from the first, not from
 * the meme this visitor actually saw last time.
 */
export default function BudgetNotice({ message }: { message: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const picked = useRef<string | null>(null);

  useEffect(() => {
    if (!picked.current) picked.current = pickBudgetMeme();
    setSrc(picked.current);
  }, []);

  return (
    <div className="flex flex-col gap-2 max-w-xs" role="status">
      {src && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={message} className="w-full rounded-xl border border-border" />
      )}
      <p className="text-foreground text-xs bg-ink-1 border border-border rounded-xl px-3 py-2">
        {message}
      </p>
    </div>
  );
}
