"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";

/**
 * An animated image's first frame, drawn once to a canvas so it never
 * moves. Sized like an <img>: the caller's classes decide how far it
 * scales down. Passing the image's natural size up front gives the canvas
 * its real shape before the frame is drawn.
 */
export function StillImage({
  src,
  alt,
  className,
  width,
  height,
}: {
  src: string;
  alt: string;
  className: string;
  width?: number;
  height?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      canvas.getContext("2d")?.drawImage(img, 0, 0);
    };
    img.src = src;
  }, [src]);
  // An empty alt means decorative, as with <img alt="">: hidden from
  // assistive tech rather than an image with no name.
  const a11y = alt ? { role: "img", "aria-label": alt } : { "aria-hidden": true };
  return <canvas ref={canvasRef} width={width} height={height} {...a11y} className={className} />;
}

const isGifSrc = (src: string) => /\.gif(?:$|\?)/i.test(src);

/**
 * An <img> that holds still when the viewer asks for reduced motion: an
 * animated GIF shows its first frame, with no Play control. For small or
 * secondary images (thumbnails, Arc's template); a meme itself goes through
 * MemeDisplay, which offers Play. Waits for mount so the server's markup
 * and the first client render agree.
 */
export function MotionSafeImg({ src, alt, className }: { src: string; alt: string; className: string }) {
  const reduceMotion = useReducedMotion();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (mounted && reduceMotion && isGifSrc(src)) return <StillImage src={src} alt={alt} className={className} />;
  // eslint-disable-next-line @next/next/no-img-element -- natural ratio, any origin
  return <img src={src} alt={alt} className={className} />;
}
