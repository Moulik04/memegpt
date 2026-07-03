"use client";

import Link from "next/link";
import { ChatWindow } from "@/components/ChatWindow";

export default function Home() {
  return (
    <div className="flex flex-col h-dvh">
      {/* Header */}
      <header className="shrink-0 flex items-center justify-between px-4 py-3
                         border-b border-gray-800/60 bg-gray-950/80 backdrop-blur-sm">
        <div>
          <h1 className="text-xl font-extrabold tracking-tight gradient-text leading-none">
            MemeGPT
          </h1>
          <p className="text-[11px] text-gray-600 mt-0.5">I only communicate in memes.</p>
        </div>
        <Link
          href="/share"
          className="text-xs text-brand-400 border border-brand-700/50 rounded-full
                     px-3 py-1.5 hover:bg-brand-500/10 transition-colors"
        >
          ↗ Share Mode
        </Link>
      </header>

      {/* Chat fills remaining height */}
      <div className="flex-1 min-h-0 flex flex-col max-w-2xl w-full mx-auto">
        <ChatWindow />
      </div>
    </div>
  );
}
