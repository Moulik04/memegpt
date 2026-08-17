"use client";

import { memeImageUrl } from "@/lib/api";
import { PixelRevealImage } from "./reveals/PixelRevealImage";

interface Props {
  url: string;
  alt?: string;
}

export function MemeDisplay({ url, alt = "meme" }: Props) {
  const src = url.startsWith("http") ? url : memeImageUrl(url);

  return (
    <div className="meme-reveal mt-2 rounded-xl overflow-hidden border border-gray-700/60 flex justify-center">
      <PixelRevealImage src={src} alt={alt} />
    </div>
  );
}
