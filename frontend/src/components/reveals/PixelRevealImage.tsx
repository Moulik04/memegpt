"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";

interface Props {
  src: string;
  alt?: string;
  gridSize?: number;
  className?: string;
  /** Overrides the default max-h-[65vh] — viewport-relative height is
   * wrong for a caller with its own fixed-size stage (HeroLoop), where a
   * consistent box matters more than filling available viewport space. */
  maxHeightClassName?: string;
}

/**
 * A grid of cells over the image, staggered opacity 1→0 via GSAP to
 * cross-dissolve cell-by-cell into the real image instead of one flat
 * fade — the actual "something just got made for you" reveal moment.
 * Mechanic adapted from reactbits.dev's Pixel Transition (grid-crossfade
 * idea), re-implemented directly rather than copied — re-expressed in our
 * own dark tokens (the source uses white cells; ours uses --ink-1) per
 * the project's sourcing rule. Validated against two alternatives (a
 * WebGL halftone reveal) in a live side-by-side before this one was
 * picked.
 *
 * `object-contain`, not `object-cover`: memes have wildly variable aspect
 * ratios (wide comics, portrait panels) and cropping one can cut off the
 * caption or the joke itself — MemeDisplay's existing behavior (fit
 * inside max-h-[65vh], never crop) is preserved exactly, just wrapped
 * with the reveal grid instead of replaced.
 */
export function PixelRevealImage({
  src,
  alt = "",
  gridSize = 8,
  className,
  maxHeightClassName = "max-h-[65vh]",
}: Props) {
  const gridRef = useRef<HTMLDivElement>(null);
  const cells = Array.from({ length: gridSize * gridSize });

  useEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const children = Array.from(el.children);

    if (reduced) {
      gsap.set(children, { opacity: 0 });
      return;
    }

    gsap.set(children, { opacity: 1 });
    const tween = gsap.to(children, {
      opacity: 0,
      duration: 0.35,
      ease: "power1.out",
      stagger: {
        each: 0.012,
        from: "random",
      },
      delay: 0.15,
    });
    return () => {
      tween.kill();
    };
    // Re-run whenever a new image lands, keyed by src at the call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  return (
    <div className={`relative inline-block ${className ?? ""}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        className={`block w-auto h-auto max-w-full ${maxHeightClassName} object-contain`}
      />
      <div
        ref={gridRef}
        className="absolute inset-0 grid pointer-events-none"
        style={{ gridTemplateColumns: `repeat(${gridSize}, 1fr)`, gridTemplateRows: `repeat(${gridSize}, 1fr)` }}
      >
        {cells.map((_, i) => (
          <div key={i} className="bg-ink-1" />
        ))}
      </div>
    </div>
  );
}
