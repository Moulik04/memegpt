"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { postFeedback, sendChatImageStream, sendChatStream } from "@/lib/api";
import { MessageBubble } from "./MessageBubble";
import { ThinkingBubble } from "./ThinkingBubble";
import type { ChatMessage, MemeItem, SSEEvent } from "@/types";

const EXAMPLE_PROMPTS = [
  "waiting for my PR to get reviewed for 3 days",
  "my plan was going great then suddenly it wasn't",
  "me vs my alarm clock at 7am",
  "when the deploy finally works on first try",
  "my friend after 4 drinks claiming he's sober",
  "my manager asking who broke production",
];

// Client-side only — a fast-fail UX nicety, NOT a security control. The
// real limit is enforced server-side by uploads/safe_ingest.py.
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MEME_COUNT_OPTIONS = [2, 3, 4, 5];

interface ThinkingState { message: string }

interface PendingImage {
  file: File;
  previewUrl: string;
}

export function ChatWindow() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [thinking, setThinking] = useState<ThinkingState | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [memeCount, setMemeCount] = useState<number | undefined>(undefined);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  useEffect(() => {
    // Revoke every pending preview URL whenever the set changes or the
    // component unmounts, so we don't leak blob URLs.
    return () => {
      pendingImages.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
  }, [pendingImages]);

  const handleFeedback = useCallback(
    async (meme: MemeItem, rating: "up" | "down") => {
      // meme.situationText is the specific segmented context that produced
      // THIS meme — not the shared original submission — so feedback on
      // different memes in the same multi-meme batch write distinct
      // few-shot examples instead of colliding on the same ChromaDB doc id
      // (examples_store.upsert_example keys purely on user_message text).
      await postFeedback({
        conversation_id: conversationId,
        template_id: meme.templateId || "",
        texts: {},
        rating,
        user_message: meme.situationText,
      }).catch(() => {});
    },
    [conversationId],
  );

  function clearPendingImages() {
    pendingImages.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    setPendingImages([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removePendingImage(index: number) {
    setPendingImages((prev) => {
      const target = prev[index];
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  }

  function handleFilesSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    const oversized = files.find((f) => f.size > MAX_IMAGE_BYTES);
    if (oversized) {
      setError("One of those images is over 10MB — try smaller ones.");
      e.target.value = "";
      return;
    }
    setPendingImages((prev) => [
      ...prev,
      ...files.map((file) => ({ file, previewUrl: URL.createObjectURL(file) })),
    ]);
    setError(null);
    e.target.value = "";
  }

  async function submit(text: string) {
    const images = pendingImages;
    if ((!text.trim() && images.length === 0) || loading) return;

    const userMsg: ChatMessage = {
      role: "user",
      content:
        text.trim() ||
        (images.length ? `[${images.length} image${images.length > 1 ? "s" : ""} attached]` : ""),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    clearPendingImages();
    setLoading(true);
    setError(null);
    setThinking({ message: "Reading your vibe…" });

    // Accumulated locally (not React state) across the whole submission —
    // the grouped multi-meme bubble is only pushed once, after the stream
    // ends, rather than growing one meme at a time.
    const collected: MemeItem[] = [];
    let plainReply: string | null = null;

    try {
      const onEvent = (event: SSEEvent) => {
        if (event.type === "thinking") {
          const progress =
            event.total && event.total > 1 ? ` (${(event.index ?? 0) + 1}/${event.total})` : "";
          setThinking({ message: `${event.message}${progress}` });
        } else if (event.type === "done") {
          setConversationId(event.conversation_id);
          if (event.message.meme_url) {
            collected.push({
              url: event.message.meme_url,
              templateId: event.template_used,
              situationText: event.message.content,
            });
          } else {
            // A graceful text-only reply (e.g. vision unavailable) rather
            // than a meme — still worth showing, just not as a carousel.
            plainReply = event.message.content;
          }
        } else if (event.type === "error") {
          setError(event.message);
        }
        // batch_done needs no handling here — finalization below runs once
        // the stream itself ends, which covers every exit path (a full
        // multi-meme batch, an early single-error abort, or a graceful
        // degrade reply) the same way.
      };

      if (images.length > 0) {
        await sendChatImageStream(
          images.map((p) => p.file),
          { message: text.trim() || undefined, conversationId, memeCount },
          onEvent,
        );
      } else {
        await sendChatStream(text.trim(), conversationId, onEvent, memeCount);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (collected.length > 0) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "", memes: collected, timestamp: new Date().toISOString() },
        ]);
      } else if (plainReply) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: plainReply as string, timestamp: new Date().toISOString() },
        ]);
      }
      setLoading(false);
      setThinking(null);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(input);
  }

  function handlePromptChip(prompt: string) {
    setInput(prompt);
    inputRef.current?.focus();
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 chat-scroll">
        {messages.length === 0 && !thinking && (
          <div className="flex flex-col items-center justify-center h-full gap-6 py-8">
            <div className="text-center">
              <p className="text-gray-500 text-sm">Say anything — I&apos;ll reply in memes.</p>
              <p className="text-gray-600 text-xs mt-1">
                Or pick a prompt below, attach photos, or paste a whole conversation ↓
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center max-w-sm">
              {EXAMPLE_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => handlePromptChip(p)}
                  className="prompt-chip"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            onFeedback={
              msg.role === "assistant" && msg.memes && msg.memes.length > 0
                ? (meme, rating) => handleFeedback(meme, rating)
                : undefined
            }
          />
        ))}

        {thinking && <ThinkingBubble message={thinking.message} />}

        {error && (
          <div className="flex justify-start mb-3">
            <p className="text-red-400 text-xs bg-red-900/20 border border-red-800/40
                          rounded-xl px-3 py-2 max-w-[80%]">
              {error}
            </p>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="shrink-0 border-t border-gray-800/60 px-3 py-3">
        {pendingImages.length > 0 && (
          <div className="flex items-center gap-2 mb-2 px-1 overflow-x-auto">
            {pendingImages.map((p, i) => (
              <div key={i} className="relative shrink-0">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={p.previewUrl}
                  alt="Attached preview"
                  className="w-10 h-10 rounded-lg object-cover border border-gray-700"
                />
                <button
                  type="button"
                  onClick={() => removePendingImage(i)}
                  className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-gray-900
                             border border-gray-700 text-gray-400 hover:text-gray-200
                             text-[10px] flex items-center justify-center leading-none"
                  title="Remove"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={handleFilesSelected}
            disabled={loading}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={loading}
            title="Attach photos"
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-xl
                       border border-gray-800 text-gray-400 hover:text-gray-200
                       hover:border-gray-600 disabled:opacity-40 transition-colors"
          >
            📎
          </button>
          <select
            value={memeCount ?? ""}
            onChange={(e) => setMemeCount(e.target.value ? Number(e.target.value) : undefined)}
            disabled={loading}
            title="Number of memes"
            className="shrink-0 bg-[#13131e] border border-gray-800 rounded-xl px-2 py-2.5
                       text-xs text-gray-400 focus:outline-none focus:border-brand-600
                       disabled:opacity-40 transition-colors"
          >
            <option value="">Auto</option>
            {MEME_COUNT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} memes
              </option>
            ))}
          </select>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              pendingImages.length > 0 ? "Add a caption (optional)…" : "Type a message…"
            }
            disabled={loading}
            className="flex-1 bg-[#13131e] border border-gray-800 rounded-xl px-4 py-2.5
                       text-sm placeholder-gray-600 focus:outline-none focus:border-brand-600
                       disabled:opacity-50 transition-colors"
          />
          <button
            type="submit"
            disabled={loading || (!input.trim() && pendingImages.length === 0)}
            className="bg-brand-600 hover:bg-brand-700 disabled:opacity-40 transition-colors
                       text-white text-sm font-semibold rounded-xl px-4 py-2.5 shrink-0"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
