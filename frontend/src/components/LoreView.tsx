"use client";

import { useCallback, useRef, useState } from "react";
import { postFeedback } from "@/lib/api";
import { useMemeStream } from "@/hooks/useMemeStream";
import { FeedbackButtons } from "./FeedbackButtons";
import { MemeDisplay } from "./MemeDisplay";
import { ShareButtons } from "./ShareButtons";
import { ThinkingBubble } from "./ThinkingBubble";
import type { MemeItem } from "@/types";

const MEME_COUNT_OPTIONS = [2, 3, 4, 5];
const MAX_IMAGE_BYTES = 10 * 1024 * 1024; // client-side UX nicety only, see uploads/safe_ingest.py

interface PendingImage {
  file: File;
  previewUrl: string;
}

type FeedEntry =
  | { kind: "meme"; meme: MemeItem; votedKey: string }
  | { kind: "text"; content: string; key: string };

/**
 * Lore — the surface for big context dumps: paste a whole conversation,
 * upload a stack of screenshots, get several memes back. Every meme from
 * every submission renders as its own permanently-visible card in a flat
 * feed (not a carousel, not grouped chat bubbles) — each independently
 * viewable, shareable, and feedback-able, deliberately unlike Chat's
 * swipeable multi-meme carousel.
 */
export function LoreView() {
  const [text, setText] = useState("");
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [memeCount, setMemeCount] = useState<number | undefined>(undefined);
  const [feed, setFeed] = useState<FeedEntry[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { loading, thinking, error, plan, conversationId, submitText, submitImages } = useMemeStream();

  const handleFeedback = useCallback(
    async (meme: MemeItem, rating: "up" | "down") => {
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

  function addFiles(files: File[]) {
    if (files.length === 0) return;
    const oversized = files.find((f) => f.size > MAX_IMAGE_BYTES);
    if (oversized) {
      setLocalError("One of those images is over 10MB — try smaller ones.");
      return;
    }
    setPendingImages((prev) => [
      ...prev,
      ...files.map((file) => ({ file, previewUrl: URL.createObjectURL(file) })),
    ]);
    setLocalError(null);
  }

  function removePendingImage(index: number) {
    setPendingImages((prev) => {
      const target = prev[index];
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  }

  function clearPendingImages() {
    pendingImages.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    setPendingImages([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleTextareaInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 400)}px`;
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    addFiles(Array.from(e.dataTransfer.files ?? []).filter((f) => f.type.startsWith("image/")));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if ((!text.trim() && pendingImages.length === 0) || loading) return;

    const images = pendingImages;
    const submittedText = text.trim();
    setText("");
    clearPendingImages();
    setLocalError(null);
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const { memes, plainReply } =
      images.length > 0
        ? await submitImages(images.map((p) => p.file), submittedText || undefined, memeCount)
        : await submitText(submittedText, memeCount);

    if (memes.length > 0) {
      setFeed((prev) => [
        ...prev,
        ...memes.map((meme, i) => ({
          kind: "meme" as const,
          meme,
          votedKey: `${Date.now()}-${i}`,
        })),
      ]);
    } else if (plainReply) {
      setFeed((prev) => [...prev, { kind: "text", content: plainReply, key: `${Date.now()}` }]);
    }
  }

  const displayError = localError ?? error;

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 chat-scroll">
      <div className="max-w-2xl mx-auto flex flex-col gap-4">
        {/* Composer */}
        <form
          onSubmit={handleSubmit}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          className={`rounded-2xl border-2 border-dashed p-4 flex flex-col gap-3 transition-colors ${
            dragActive ? "border-brand-500 bg-brand-500/5" : "border-gray-800 bg-[#13131e]"
          }`}
        >
          <textarea
            ref={textareaRef}
            value={text}
            onChange={handleTextareaInput}
            placeholder="Paste a whole conversation, a group chat thread, anything with a bunch of moments in it…"
            disabled={loading}
            rows={4}
            className="w-full bg-transparent resize-none text-sm placeholder-gray-600
                       focus:outline-none disabled:opacity-50"
          />

          {pendingImages.length > 0 && (
            <div className="flex items-center gap-2 overflow-x-auto">
              {pendingImages.map((p, i) => (
                <div key={i} className="relative shrink-0">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={p.previewUrl}
                    alt="Attached preview"
                    className="w-14 h-14 rounded-lg object-cover border border-gray-700"
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

          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => {
                addFiles(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
              disabled={loading}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading}
              title="Attach or drop screenshots"
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
              className="shrink-0 bg-gray-900 border border-gray-800 rounded-xl px-2 py-2.5
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
            <div className="flex-1" />
            <button
              type="submit"
              disabled={loading || (!text.trim() && pendingImages.length === 0)}
              className="bg-brand-600 hover:bg-brand-700 disabled:opacity-40 transition-colors
                         text-white text-sm font-semibold rounded-xl px-4 py-2.5 shrink-0"
            >
              Drop the lore
            </button>
          </div>

          <p className="text-[10px] text-gray-600">
            Processed, never stored — images are deleted after your memes are generated.
          </p>
        </form>

        {displayError && (
          <p className="text-red-400 text-xs bg-red-900/20 border border-red-800/40
                        rounded-xl px-3 py-2">
            {displayError}
          </p>
        )}

        {plan && plan.total > 1 && (
          <div className="rounded-2xl bg-[#13131e] border border-gray-800/60 px-4 py-3">
            <p className="text-[10px] text-gray-500 mb-2 uppercase tracking-wide">
              Found {plan.total} moments worth memeing
            </p>
            <ul className="flex flex-col gap-1.5">
              {plan.situations.map((situation, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <span
                    className={
                      plan.doneIndices.has(i) ? "text-brand-400" : "text-gray-600"
                    }
                  >
                    {plan.doneIndices.has(i) ? "✓" : "○"}
                  </span>
                  <span className={plan.doneIndices.has(i) ? "text-gray-400" : "text-gray-600"}>
                    {situation}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {thinking && <ThinkingBubble message={thinking.message} />}

        {/* Flat feed — every meme its own permanently-visible card */}
        <div className="flex flex-col gap-4">
          {feed.map((entry) =>
            entry.kind === "meme" ? (
              <div
                key={entry.votedKey}
                className="rounded-2xl bg-[#13131e] border border-gray-800/60 p-3 shadow-lg"
              >
                <MemeDisplay url={entry.meme.url} alt={entry.meme.situationText} />
                <p className="text-xs text-gray-400 mt-2 px-0.5">{entry.meme.situationText}</p>
                <div className="flex items-center justify-between mt-1">
                  <ShareButtons memeUrl={entry.meme.url} />
                  <FeedbackButtons onFeedback={(rating) => handleFeedback(entry.meme, rating)} />
                </div>
              </div>
            ) : (
              <p
                key={entry.key}
                className="text-sm text-gray-300 bg-[#13131e] border border-gray-800/60
                           rounded-2xl px-4 py-3"
              >
                {entry.content}
              </p>
            ),
          )}
        </div>
      </div>
    </div>
  );
}
