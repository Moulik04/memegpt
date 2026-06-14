"use client";

import Image from "next/image";
import { memeImageUrl } from "@/lib/api";

interface Props {
  url: string;
  alt?: string;
}

export function MemeDisplay({ url, alt = "meme" }: Props) {
  const src = url.startsWith("http") ? url : memeImageUrl(url);

  return (
    <div className="meme-reveal mt-2 rounded-xl overflow-hidden border border-gray-700 max-w-sm">
      <Image
        src={src}
        alt={alt}
        width={500}
        height={400}
        className="w-full h-auto object-contain"
        unoptimized
      />
    </div>
  );
}
