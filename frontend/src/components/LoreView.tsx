"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { createConversation, getConversationMessages, postFeedback } from "@/lib/api";
import { useMemeStream } from "@/hooks/useMemeStream";
import { useConversation } from "@/lib/ConversationContext";
import { useAuth } from "@/hooks/useAuth";
import { MemeCard } from "./MemeCard";
import { ThinkingBubble } from "./ThinkingBubble";
import { DecryptedText } from "./DecryptedText";
import type { MemeItem, PersistedMessage } from "@/types";

const BACKEND_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

function base64ToFile(dataBase64: string, filename: string, contentType: string): File {
  const byteChars = atob(dataBase64);
  const bytes = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i);
  return new File([bytes], filename, { type: contentType });
}

const MEME_COUNT_OPTIONS = [2, 3, 4, 5];
const MAX_IMAGE_BYTES = 10 * 1024 * 1024; // matches config.py's max_image_bytes
const MAX_IMAGES_PER_REQUEST = 6; // matches config.py's max_images_per_request
// Matches config.py's max_dump_chars default — a UX nicety only, the real
// clamp is server-side (routers/chat.py's _clamp_dump_text). Never blocks
// submission, just sets expectations.
const MAX_DUMP_CHARS = 20000;
// Matches config.py's segmentation_text_threshold_chars/max_memes_per_request
// defaults — below this length the backend takes the zero-LLM-call fast
// path (one situation, no segmentation call at all), so an estimate here
// would just be noise.
const SEGMENTATION_TEXT_THRESHOLD_CHARS = 240;
const MAX_MEMES_PER_REQUEST = 5;

// A rough proxy only — paragraph breaks are a cheap client-side heuristic,
// not a reimplementation of the backend's actual semantic segmentation
// call (nlp/segmentation.py's segment_contexts()). The two are allowed to
// disagree; this exists to set expectations before submit, not to predict
// the real result.
function estimateMomentCount(text: string): number {
  const blocks = text
    .trim()
    .split(/\n\s*\n/)
    .filter((block) => block.trim().length > 0);
  return Math.max(1, Math.min(MAX_MEMES_PER_REQUEST, blocks.length));
}

interface PendingImage {
  file: File;
  previewUrl: string;
}

type FeedEntry =
  | { kind: "meme"; meme: MemeItem; votedKey: string }
  | { kind: "text"; content: string; key: string };

// Growth Phase H, Stage 3 — Lore's feed never showed user-echo entries
// (handleSubmit below only ever pushes results, not the submission itself),
// so hydration keeps that: only assistant rows become feed entries.
function groupPersistedFeed(rows: PersistedMessage[]): FeedEntry[] {
  return rows
    .filter((r) => r.role === "assistant")
    .map((r) =>
      r.meme_url
        ? {
            kind: "meme" as const,
            meme: { url: r.meme_url, situationText: r.content, memeId: r.meme_id ?? undefined },
            votedKey: r.id,
          }
        : { kind: "text" as const, content: r.content, key: r.id },
    );
}

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
  // Growth Phase C — strictly opt-in, off by default, and deliberately NOT
  // reset per-submission in handleSubmit below: this means "remember this
  // whole conversation," not "remember just this one message."
  const [rememberLore, setRememberLore] = useState(false);
  const [feed, setFeed] = useState<FeedEntry[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { user } = useAuth();
  const { conversationRowId, setConversationRowId, bumpRefresh } = useConversation();
  const { loading, thinking, error, plan, conversationId, submitText, submitImages } = useMemeStream(
    "lore",
    conversationRowId,
  );
  const router = useRouter();

  // Hydrate from a persisted conversation when one becomes selected, reset
  // to an empty feed when it's cleared — same precedent as ChatWindow.tsx.
  useEffect(() => {
    if (!conversationRowId) {
      setFeed([]);
      return;
    }
    let cancelled = false;
    getConversationMessages(conversationRowId).then((rows) => {
      if (!cancelled) setFeed(groupPersistedFeed(rows));
    });
    return () => {
      cancelled = true;
    };
  }, [conversationRowId]);

  // Consume a share-target handoff (?intake=<token>) on mount, if present.
  // Reads window.location.search directly rather than next/navigation's
  // useSearchParams() to avoid that hook's Suspense-boundary requirement on
  // an otherwise statically-prerendered page. Pre-fills the composer —
  // never auto-submits — then strips the query param so a refresh doesn't
  // retry an already-consumed (single-use) token.
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("intake");
    if (!token) return;

    (async () => {
      try {
        const res = await fetch(`${BACKEND_BASE}/share-intake/${token}/`);
        if (!res.ok) return;
        const data = await res.json();

        if (data.text) setText((prev) => prev || data.text);

        const newImages: PendingImage[] = (data.images ?? []).map(
          (img: { filename: string; content_type: string; data_base64: string }) => {
            const file = base64ToFile(img.data_base64, img.filename, img.content_type);
            return { file, previewUrl: URL.createObjectURL(file) };
          },
        );
        if (newImages.length > 0) setPendingImages((prev) => [...prev, ...newImages]);
      } catch {
        // Worst case the user just re-shares or attaches manually.
      } finally {
        router.replace("/lore");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFeedback = useCallback(
    async (meme: MemeItem, rating: "up" | "down") => {
      await postFeedback({
        conversation_id: conversationId,
        template_id: meme.templateId || "",
        texts: {},
        rating,
        user_message: meme.situationText,
        meme_id: meme.memeId,
      }).catch(() => {});
    },
    [conversationId],
  );

  function addFiles(files: File[]) {
    if (files.length === 0) return;
    const oversized = files.find((f) => f.size > MAX_IMAGE_BYTES);
    if (oversized) {
      setLocalError(`That image is over ${MAX_IMAGE_BYTES / (1024 * 1024)}MB — try a smaller one.`);
      return;
    }
    if (pendingImages.length + files.length > MAX_IMAGES_PER_REQUEST) {
      setLocalError(`Up to ${MAX_IMAGES_PER_REQUEST} photos per message — remove some before adding more.`);
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

    // Same auto-create-on-first-message fix as ChatWindow.tsx — see that
    // file's comment for why activeConversationRowId is passed explicitly
    // rather than relying on setConversationRowId() being visible yet.
    let activeConversationRowId = conversationRowId;
    if (user && !activeConversationRowId) {
      const created = await createConversation("lore").catch(() => null);
      if (created) {
        activeConversationRowId = created.id;
        setConversationRowId(created.id);
      }
    }

    const { memes, plainReply } =
      images.length > 0
        ? await submitImages(images.map((p) => p.file), submittedText || undefined, memeCount, rememberLore, activeConversationRowId)
        : await submitText(submittedText, memeCount, rememberLore, activeConversationRowId);

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

    if (activeConversationRowId) bumpRefresh();
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
          className={`relative rounded-2xl border-2 p-4 flex flex-col gap-3 shadow-lg transition-all ${
            dragActive
              ? "border-accent border-solid bg-accent/5"
              : "border-border border-dashed bg-card focus-within:border-accent/60"
          }`}
        >
          <AnimatePresence>
            {dragActive && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2
                           rounded-2xl bg-card/95 pointer-events-none"
              >
                <span className="text-2xl">📥</span>
                <p className="text-sm font-semibold text-accent">Drop to add screenshots</p>
              </motion.div>
            )}
          </AnimatePresence>

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

          {text.length > MAX_DUMP_CHARS && (
            <p className="text-[10px] text-amber-500">
              Long lore! Using the first ~{Math.round(MAX_DUMP_CHARS / 1000)}k characters.
            </p>
          )}

          {text.length > SEGMENTATION_TEXT_THRESHOLD_CHARS && !memeCount && (
            <p className="text-[10px] text-gray-600">
              Looks like ~{estimateMomentCount(text)} moment
              {estimateMomentCount(text) === 1 ? "" : "s"} worth memeing — rough
              estimate, MemeGPT will decide for real.
            </p>
          )}

          {pendingImages.length > 0 && (
            <div className="flex items-center gap-2 overflow-x-auto">
              <AnimatePresence mode="popLayout" initial={false}>
                {pendingImages.map((p, i) => (
                  <motion.div
                    key={p.previewUrl}
                    layout
                    initial={{ opacity: 0, scale: 0.85 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.85 }}
                    transition={{ duration: 0.15 }}
                    className="relative shrink-0"
                  >
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
                  </motion.div>
                ))}
              </AnimatePresence>
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
              className="shrink-0 bg-ink-2 border border-border rounded-xl px-2 py-2.5
                         text-xs text-gray-400 focus:outline-none focus:border-accent
                         disabled:opacity-40 transition-colors"
            >
              <option value="">Auto</option>
              {MEME_COUNT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n} memes
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setRememberLore((v) => !v)}
              disabled={loading}
              title="Extract and remember this group's recurring names/running jokes for future callbacks"
              aria-pressed={rememberLore}
              className={`shrink-0 text-xs font-medium rounded-full px-3 py-2.5 transition-colors ${
                rememberLore
                  ? "bg-accent text-white"
                  : "bg-ink-2 border border-border text-gray-500 hover:text-gray-300"
              } disabled:opacity-40`}
            >
              🧠 Remember lore
            </button>
            <div className="flex-1" />
            <button
              type="submit"
              disabled={loading || (!text.trim() && pendingImages.length === 0)}
              className="bg-accent hover:bg-accent/90 disabled:opacity-40 transition-colors
                         text-white text-sm font-semibold rounded-xl px-4 py-2.5 shrink-0"
            >
              Drop the lore
            </button>
          </div>

          <p className="text-[10px] text-gray-600">
            Processed, never stored — images are deleted after your memes are generated.
            {rememberLore
              ? " Remember lore is on: short recurring names/jokes get extracted for future callbacks, never the raw text — erase anytime with Forget me."
              : " Remember lore is off by default — turn it on to let recurring names/jokes carry into future memes."}
          </p>
        </form>

        {displayError && (
          <p className="text-red-400 text-xs bg-red-900/20 border border-red-800/40
                        rounded-xl px-3 py-2">
            {displayError}
          </p>
        )}

        {plan && plan.total > 1 && (
          <div className="rounded-2xl bg-card border border-border px-4 py-3">
            <p className="text-[10px] text-gray-500 mb-2 uppercase tracking-wide">
              Found {plan.total} moments worth memeing
            </p>
            <ul className="flex flex-col gap-1.5">
              {plan.situations.map((situation, i) => (
                <li key={i} className="flex items-start gap-2 text-xs">
                  <span
                    className={
                      plan.doneIndices.has(i) ? "text-accent" : "text-gray-600"
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

        {/* Flat feed — every meme its own permanently-visible card. Each
            entry gets a staggered settle-in (capped so a long history
            doesn't queue an absurd cumulative delay) — this is where it
            matters most: one Lore submission routinely lands several memes
            at once, and watching them cascade in one after another is a
            better signal that something real happened than a batch of
            cards just appearing. */}
        <div className="flex flex-col gap-4">
          {feed.map((entry, i) => {
            const style = {
              animationDelay: `${Math.min(i, 5) * 70}ms`,
              animationFillMode: "backwards" as const,
            };
            // When several memes land from one submission, hovering one
            // dims the rest instead of leaving them all at equal visual
            // weight — draws focus to the one you're looking at without
            // hiding the others, since they're all still worth a glance.
            const dimmed = hoveredIndex !== null && hoveredIndex !== i;
            const hoverProps = {
              onMouseEnter: () => setHoveredIndex(i),
              onMouseLeave: () => setHoveredIndex(null),
            };
            return entry.kind === "meme" ? (
              <div
                key={entry.votedKey}
                className={`arrive-settle transition-[opacity,transform] duration-200 ${
                  dimmed ? "opacity-50 scale-[0.98]" : "opacity-100 scale-100"
                }`}
                style={style}
                {...hoverProps}
              >
                <MemeCard
                  url={entry.meme.url}
                  alt={entry.meme.situationText}
                  templateId={entry.meme.templateId}
                  onFeedback={(rating) => handleFeedback(entry.meme, rating)}
                />
              </div>
            ) : (
              <p
                key={entry.key}
                className={`arrive-settle text-sm text-gray-300 bg-card border border-border
                           rounded-2xl px-4 py-3 transition-[opacity,transform] duration-200 ${
                             dimmed ? "opacity-50 scale-[0.98]" : "opacity-100 scale-100"
                           }`}
                style={style}
                {...hoverProps}
              >
                <DecryptedText text={entry.content} />
              </p>
            );
          })}
        </div>
      </div>
    </div>
  );
}
