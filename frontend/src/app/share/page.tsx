"use client";

import { useState } from "react";
import Link from "next/link";
import { sendChatStream } from "@/lib/api";
import { MemeDisplay } from "@/components/MemeDisplay";
import { ShareButtons } from "@/components/ShareButtons";
import type { ChatMessage } from "@/types";

const EXAMPLES = [
  "my friend after 4 drinks saying he's totally fine",
  "waiting for my salary to hit the account",
  "me during a meeting that could've been an email",
  "when autocorrect embarrasses you in a group chat",
];

export default function SharePage() {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<ChatMessage | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    const text = input.trim();
    if (!text || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setStatus("Reading your vibe…");
    try {
      await sendChatStream(text, undefined, (event) => {
        if (event.type === "thinking") setStatus(event.message);
        else if (event.type === "done") {
          setResult({ ...event.message, template_id: event.template_used });
          setStatus("");
        } else if (event.type === "error") {
          setError(event.message);
          setStatus("");
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate");
    } finally {
      setLoading(false);
      setStatus("");
    }
  }

  function reset() {
    setResult(null);
    setInput("");
    setError(null);
  }

  return (
    <div className="min-h-dvh flex flex-col bg-gray-950">
      {/* Header */}
      <header className="shrink-0 flex items-center justify-between px-4 py-3
                         border-b border-gray-800/60">
        <div>
          <h1 className="text-lg font-extrabold gradient-text leading-none">MemeGPT</h1>
          <p className="text-[11px] text-gray-600 mt-0.5">Share Extension</p>
        </div>
        <Link
          href="/"
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          ← Chat Mode
        </Link>
      </header>

      <main className="flex-1 flex flex-col max-w-lg w-full mx-auto px-4 py-6 gap-6">

        {!result ? (
          /* ── Input state ── */
          <>
            <div className="text-center">
              <p className="text-gray-300 font-medium">What&apos;s the vibe?</p>
              <p className="text-gray-500 text-sm mt-1">
                Describe your situation or paste chat context.
              </p>
            </div>

            {/* Textarea */}
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. my friend just sent a voice note that's 8 minutes long"
              disabled={loading}
              rows={4}
              className="w-full bg-[#13131e] border border-gray-800 rounded-xl px-4 py-3
                         text-sm placeholder-gray-600 focus:outline-none focus:border-brand-600
                         disabled:opacity-50 resize-none transition-colors"
            />

            {/* Generate button */}
            <button
              onClick={generate}
              disabled={!input.trim() || loading}
              className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-700
                         disabled:opacity-40 text-white font-semibold text-sm
                         transition-colors flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-white dot-1 block" />
                  <span className="w-1.5 h-1.5 rounded-full bg-white dot-2 block" />
                  <span className="w-1.5 h-1.5 rounded-full bg-white dot-3 block" />
                  <span className="ml-1 text-white/80 text-xs">{status}</span>
                </>
              ) : (
                "Generate Meme"
              )}
            </button>

            {/* Error */}
            {error && (
              <p className="text-red-400 text-xs text-center">{error}</p>
            )}

            {/* Example chips */}
            <div className="mt-2">
              <p className="text-gray-600 text-xs mb-2 text-center">Try an example</p>
              <div className="flex flex-wrap gap-2 justify-center">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    onClick={() => setInput(ex)}
                    className="prompt-chip"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : (
          /* ── Result state ── */
          <>
            <div className="rounded-2xl bg-[#13131e] border border-gray-800/60 p-4">
              <MemeDisplay url={result.meme_url!} />

              {result.template_id && (
                <p className="text-[10px] text-gray-600 mt-2">
                  {result.template_id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </p>
              )}

              {/* Share buttons — large variant for the share page */}
              <ShareButtons memeUrl={result.meme_url!} large />
            </div>

            {/* Try again */}
            <button
              onClick={reset}
              className="text-sm text-gray-500 hover:text-gray-300 transition-colors
                         border border-gray-800 rounded-xl py-2.5"
            >
              ↺ Generate another
            </button>
          </>
        )}
      </main>
    </div>
  );
}
