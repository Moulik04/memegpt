"use client";

import { useState } from "react";
import { memeImageUrl } from "@/lib/api";

interface Props {
  memeUrl: string;
  large?: boolean; // for the /share page's big primary button
}

export function ShareButtons({ memeUrl, large = false }: Props) {
  const [copying, setCopying] = useState(false);
  const [copied, setCopied] = useState(false);

  const fullUrl = memeUrl.startsWith("http") ? memeUrl : memeImageUrl(memeUrl);
  const canShare = typeof navigator !== "undefined" && !!navigator.share;

  async function fetchBlob(): Promise<Blob> {
    const res = await fetch(fullUrl);
    return res.blob();
  }

  async function handleDownload() {
    try {
      const blob = await fetchBlob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = "meme.png";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch {
      window.open(fullUrl, "_blank");
    }
  }

  async function handleCopy() {
    if (copying) return;
    setCopying(true);
    try {
      const blob = await fetchBlob();
      await navigator.clipboard.write([
        new ClipboardItem({ "image/png": blob }),
      ]);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      try {
        await navigator.clipboard.writeText(fullUrl);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {}
    } finally {
      setCopying(false);
    }
  }

  async function handleShare() {
    try {
      const blob = await fetchBlob();
      const file = new File([blob], "meme.png", { type: "image/png" });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: "MemeGPT",
          text: "Check this meme 😂",
        });
        return;
      }
    } catch {}
    if (navigator.share) {
      await navigator.share({ url: fullUrl, title: "MemeGPT" }).catch(() => {});
    }
  }

  if (large) {
    return (
      <div className="flex flex-col gap-3 w-full mt-4">
        {canShare && (
          <button
            onClick={handleShare}
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-700
                       text-white font-semibold text-sm transition-colors"
          >
            ↗ Share to WhatsApp / Instagram / Snapchat
          </button>
        )}
        <div className="flex gap-2">
          <button
            onClick={handleDownload}
            className="flex-1 py-2.5 rounded-xl border border-gray-700 hover:border-gray-500
                       text-gray-300 text-sm transition-colors hover:bg-white/5"
          >
            ↓ Download
          </button>
          <button
            onClick={handleCopy}
            disabled={copying}
            className="flex-1 py-2.5 rounded-xl border border-gray-700 hover:border-gray-500
                       text-gray-300 text-sm transition-colors hover:bg-white/5 disabled:opacity-50"
          >
            {copied ? "✓ Copied!" : copying ? "Copying…" : "⎘ Copy Image"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-0.5 mt-1">
      <button onClick={handleDownload} className="action-btn" title="Download">
        ↓ Save
      </button>
      <span className="text-gray-700 text-xs">·</span>
      <button
        onClick={handleCopy}
        disabled={copying}
        className="action-btn"
        title="Copy image"
      >
        {copied ? "✓ Copied" : copying ? "…" : "⎘ Copy"}
      </button>
      {canShare && (
        <>
          <span className="text-gray-700 text-xs">·</span>
          <button
            onClick={handleShare}
            className="action-btn action-btn-primary"
            title="Share"
          >
            ↗ Share
          </button>
        </>
      )}
    </div>
  );
}
