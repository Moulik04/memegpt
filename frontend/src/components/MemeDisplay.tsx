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
    <div className="meme-reveal mt-2 rounded-xl overflow-hidden border border-gray-700/60 flex justify-center">
      <Image
        src={src}
        alt={alt}
        width={600}
        height={500}
        className="w-auto h-auto max-w-full max-h-[65vh] object-contain"
        unoptimized
      />
    </div>
  );
}
