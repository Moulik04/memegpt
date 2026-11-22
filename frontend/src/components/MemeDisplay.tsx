"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { memeImageUrl } from "@/lib/api";
import { Dialog, DialogClose, DialogContent, DialogTitle } from "@/components/ui/dialog";

interface Props {
  url: string;
  alt?: string;
  /** The tallest the image may render in place. The caller's slot decides. */
  maxHeightClassName?: string;
  /** Replaces the default wrapper classes, which center the frame. */
  className?: string;
  /** Shown above the image in the full-size view, such as the message line. */
  heading?: ReactNode;
  /** Shown under the image in the full-size view, such as the action row. */
  footer?: ReactNode;
}

type LoadState = "loading" | "ready" | "broken";

// Images this page has already shown. A meme that moves to a new place,
// as Chat's lead does into Earlier, mounts again: starting it as ready
// keeps the loading box from flashing, and gives a layout animation the
// image's real size to measure.
const loadedSources = new Set<string>();

/**
 * The shared meme frame. Every meme sits at its own natural ratio on the
 * same light gray mat with a hairline edge, and is never cropped or
 * stretched: the image only scales down to fit the caller's width and
 * maxHeightClassName. Captions and the watermark are part of the image.
 * Meme images don't animate in. Activating the image opens it full size.
 */
export function MemeDisplay({
  url,
  alt = "meme",
  maxHeightClassName = "max-h-[65vh]",
  className = "mt-2 flex justify-center",
  heading,
  footer,
}: Props) {
  const base = url.startsWith("http") ? url : memeImageUrl(url);
  const [attempt, setAttempt] = useState(0);
  const src = attempt === 0 ? base : `${base}${base.includes("?") ? "&" : "?"}retry=${attempt}`;
  const [state, setState] = useState<LoadState>(() => (loadedSources.has(src) ? "ready" : "loading"));
  const [open, setOpen] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    // An image already in the cache can finish before React attaches
    // onLoad, so check once after mount too.
    const img = imgRef.current;
    if (img?.complete) {
      if (img.naturalWidth > 0) loadedSources.add(src);
      setState(img.naturalWidth > 0 ? "ready" : "broken");
    } else {
      setState(loadedSources.has(src) ? "ready" : "loading");
    }
  }, [src]);

  return (
    <div className={className}>
      {state === "broken" ? (
        <div
          role="alert"
          className="w-full max-w-md bg-meme-mat border border-meme-edge px-4 py-8 flex flex-col
                     items-center gap-2 text-center"
        >
          <p className="text-base text-foreground">MemeGPT couldn&apos;t load this meme.</p>
          <button
            type="button"
            onClick={() => setAttempt((n) => n + 1)}
            className="min-h-11 px-3 text-base font-medium text-foreground underline decoration-brand
                       decoration-2 underline-offset-4"
          >
            Try again
          </button>
        </div>
      ) : (
        <figure className="max-w-full bg-meme-mat border border-meme-edge p-2 md:p-3">
          {state === "loading" && (
            <div
              aria-label="Loading meme"
              role="img"
              className={`w-[min(28rem,80vw)] aspect-[4/3] ${maxHeightClassName}`}
            />
          )}
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label="Open full size"
            className={`block max-w-full cursor-zoom-in ${state === "loading" ? "hidden" : ""}`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- natural size, any origin */}
            <img
              ref={imgRef}
              src={src}
              alt={alt}
              onLoad={() => {
                loadedSources.add(src);
                setState("ready");
              }}
              onError={() => setState("broken")}
              className={`block w-auto h-auto max-w-full ${maxHeightClassName} border border-meme-edge`}
            />
          </button>
        </figure>
      )}

      {/* Centered by left-0 right-0 mx-auto, not left-1/2 plus a translate:
          a shrink-to-fit box that starts at 50% can never be wider than the
          other half of the viewport. */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          showCloseButton={false}
          className="left-0 right-0 mx-auto translate-x-0 w-fit max-w-[calc(100vw-2rem)] sm:max-w-[calc(100vw-4rem)]
                     p-3 gap-2 bg-background"
        >
          <DialogTitle className="sr-only">{alt}</DialogTitle>
          {heading}
          <div className="bg-meme-mat border border-meme-edge p-2 md:p-3 justify-self-center">
            {/* eslint-disable-next-line @next/next/no-img-element -- natural size, any origin */}
            <img
              src={src}
              alt={alt}
              className={`block w-auto h-auto max-w-full border border-meme-edge ${
                heading || footer ? "max-h-[calc(100dvh-14rem)]" : "max-h-[calc(100dvh-8rem)]"
              }`}
            />
          </div>
          {footer}
          <DialogClose className="justify-self-end min-h-11 px-3 text-base font-medium text-foreground">
            Close
          </DialogClose>
        </DialogContent>
      </Dialog>
    </div>
  );
}
