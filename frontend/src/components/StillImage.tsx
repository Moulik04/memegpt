"use client";

import { useEffect, useRef } from "react";

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
  return <canvas ref={canvasRef} width={width} height={height} role="img" aria-label={alt} className={className} />;
}
