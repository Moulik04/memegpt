"use client";

import { ChatWindow } from "@/components/ChatWindow";

export default function Home() {
  return (
    <main className="flex flex-col items-center justify-center min-h-screen p-4">
      <header className="mb-6 text-center">
        <h1 className="text-4xl font-extrabold tracking-tight text-brand-500">
          MemeGPT
        </h1>
        <p className="mt-1 text-sm text-gray-400">
          I only communicate in memes.
        </p>
      </header>

      <ChatWindow />
    </main>
  );
}
