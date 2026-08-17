"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { createConversation, getConversationMessages, postFeedback } from "@/lib/api";
import { useMemeStream } from "@/hooks/useMemeStream";
import { useConversation } from "@/lib/ConversationContext";
import { useAuth } from "@/hooks/useAuth";
import { pickRandomPrompts } from "@/lib/examplePrompts";
import { MessageBubble } from "./MessageBubble";
import { ThinkingBubble } from "./ThinkingBubble";
import type { ChatMessage, MemeItem, PersistedMessage } from "@/types";

// Growth Phase H, Stage 3 — reconstructs the grouped-bubble shape a live
// SSE batch already produces (one user turn, one assistant turn whose
// `memes` array can hold several) from the flat, one-row-per-meme table
// GET /conversations/{id}/messages actually returns.
function groupPersistedMessages(rows: PersistedMessage[]): ChatMessage[] {
  const result: ChatMessage[] = [];
  let openMemes: MemeItem[] | null = null;

  for (const row of rows) {
    if (row.role === "user") {
      openMemes = null;
      result.push({ role: "user", content: row.content, timestamp: row.created_at });
      continue;
    }
    if (row.meme_url) {
      const meme: MemeItem = { url: row.meme_url, situationText: row.content, memeId: row.meme_id ?? undefined };
      if (openMemes) {
        openMemes.push(meme);
      } else {
        openMemes = [meme];
        result.push({ role: "assistant", content: "", memes: openMemes, timestamp: row.created_at });
      }
    } else {
      openMemes = null;
      result.push({ role: "assistant", content: row.content, timestamp: row.created_at });
    }
  }
  return result;
}

// Client-side only — a fast-fail UX nicety, NOT a security control. The
// real limits are enforced server-side by uploads/safe_ingest.py / config.py.
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_IMAGES_PER_REQUEST = 6; // matches config.py's max_images_per_request

interface PendingImage {
  file: File;
  previewUrl: string;
}

export function ChatWindow() {
  // Populated client-side only, after mount — pickRandomPrompts() uses
  // unseeded Math.random(), so picking it during the initial render (which
  // runs on both the server and the client during hydration) produced two
  // different chip sets and a React hydration mismatch on every page load.
  // Starting empty on both passes and filling in via useEffect keeps the
  // server and client's first render identical; the chips pop in a moment
  // after mount instead.
  const [examplePrompts, setExamplePrompts] = useState<string[]>([]);
  useEffect(() => {
    setExamplePrompts(pickRandomPrompts(6));
  }, []);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { user } = useAuth();
  const { conversationRowId, setConversationRowId, bumpRefresh } = useConversation();
  const { loading, thinking, error, conversationId, submitText, submitImages } = useMemeStream(
    "chat",
    conversationRowId,
  );
  const pendingImagesRef = useRef<PendingImage[]>([]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  // Hydrate from a persisted conversation when one becomes selected (sidebar
  // click), and reset to a blank slate when it's cleared ("New chat", or
  // switching surfaces). Anonymous use never sets conversationRowId at all,
  // so this effect is a no-op for every anonymous page load.
  useEffect(() => {
    if (!conversationRowId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    getConversationMessages(conversationRowId).then((rows) => {
      if (!cancelled) setMessages(groupPersistedMessages(rows));
    });
    return () => {
      cancelled = true;
    };
  }, [conversationRowId]);

  useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  useEffect(() => {
    // Revoke whatever's still pending (never submitted) on unmount only —
    // NOT on every pendingImages change, since a submitted message's
    // userImages keep their preview URLs alive for the life of the
    // conversation (see submit() below).
    return () => {
      pendingImagesRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
  }, []);

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
        meme_id: meme.memeId,
      }).catch(() => {});
    },
    [conversationId],
  );

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
      setLocalError(`That image is over ${MAX_IMAGE_BYTES / (1024 * 1024)}MB — try a smaller one.`);
      e.target.value = "";
      return;
    }
    if (pendingImages.length + files.length > MAX_IMAGES_PER_REQUEST) {
      setLocalError(`Up to ${MAX_IMAGES_PER_REQUEST} photos per message — remove some before adding more.`);
      e.target.value = "";
      return;
    }
    setPendingImages((prev) => [
      ...prev,
      ...files.map((file) => ({ file, previewUrl: URL.createObjectURL(file) })),
    ]);
    setLocalError(null);
    e.target.value = "";
  }

  async function submit(text: string) {
    const images = pendingImages;
    if ((!text.trim() && images.length === 0) || loading) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: text.trim(),
      userImages: images.length > 0 ? images.map((p) => p.previewUrl) : undefined,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    // Ownership of these preview URLs transfers to userMsg above — reset the
    // composer's pending state WITHOUT revoking them.
    setPendingImages([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
    setLocalError(null);

    // Auto-create a conversation on first message when signed in with none
    // active — otherwise a signed-in user who just starts typing (the
    // natural thing to do, not "click + New chat first") gets zero
    // persistence: routers/chat.py only writes messages when a verified
    // user_id AND an ownership-checked conversation_row_id are both
    // present. setConversationRowId(id) here won't be visible to
    // submitText/submitImages below in this same call (conversationRowId
    // is a plain closed-over param, React state doesn't apply until the
    // next render) — pass activeConversationRowId as an explicit override
    // instead of relying on it.
    let activeConversationRowId = conversationRowId;
    if (user && !activeConversationRowId) {
      const created = await createConversation("chat").catch(() => null);
      if (created) {
        activeConversationRowId = created.id;
        setConversationRowId(created.id);
      }
    }

    const { memes, plainReply } = images.length > 0
      ? await submitImages(images.map((p) => p.file), text.trim() || undefined, undefined, undefined, activeConversationRowId)
      : await submitText(text.trim(), undefined, undefined, activeConversationRowId);

    if (memes.length > 0) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "", memes, timestamp: new Date().toISOString() },
      ]);
    } else if (plainReply) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: plainReply, timestamp: new Date().toISOString() },
      ]);
    }

    // Growth Phase H, Stage 3 — a persisted turn just landed a title and/or
    // moved to the top of the sidebar's newest-first order; a no-op when
    // there's no active conversationRowId (anonymous use).
    if (activeConversationRowId) bumpRefresh();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(input);
  }

  function handlePromptChip(prompt: string) {
    setInput(prompt);
    inputRef.current?.focus();
  }

  const displayError = localError ?? error;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 chat-scroll">
        {messages.length === 0 && !thinking && (
          <div className="flex flex-col items-center h-full gap-10 pt-[12vh] pb-8 text-center">
            <div className="arrive-settle">
              <h2 className="headline-poster max-w-md mx-auto">
                say something.
                <br />
                get a meme <span className="hl">back.</span>
              </h2>
              <p
                className="margin-note text-sm mt-4 arrive-settle"
                style={{ animationDelay: "90ms", animationFillMode: "backwards" }}
              >
                it only speaks meme — pick a prompt below, or attach a photo ↓
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-xl">
              {examplePrompts.map((p, i) => (
                <button
                  key={p}
                  onClick={() => handlePromptChip(p)}
                  onMouseMove={(e) => {
                    // Direct DOM mutation, not React state — a mousemove
                    // handler firing dozens of times a second has no
                    // business triggering a re-render just to move a
                    // radial-gradient position.
                    const rect = e.currentTarget.getBoundingClientRect();
                    e.currentTarget.style.setProperty("--mx", `${e.clientX - rect.left}px`);
                    e.currentTarget.style.setProperty("--my", `${e.clientY - rect.top}px`);
                  }}
                  className="prompt-chip arrive-settle"
                  style={{
                    animationDelay: `${150 + i * 60}ms`,
                    animationFillMode: "backwards",
                  }}
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

        {displayError && (
          <div className="flex justify-start mb-3">
            <p className="text-destructive text-xs bg-destructive/10 border border-destructive/30
                          rounded-xl px-3 py-2 max-w-[80%]">
              {displayError}
            </p>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="shrink-0 border-t border-gray-800/60 px-3 py-3">
        {pendingImages.length > 0 && (
          <div className="flex items-center gap-2 mb-2 px-1 overflow-x-auto">
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
                    className="w-10 h-10 rounded-lg object-cover border border-gray-700"
                  />
                  <button
                    type="button"
                    onClick={() => removePendingImage(i)}
                    className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-gray-900
                               border border-gray-700 text-gray-400 hover:text-gray-200
                               text-[10px] flex items-center justify-center leading-none"
                    title="Remove"
                    aria-label="Remove image"
                  >
                    ✕
                  </button>
                </motion.div>
              ))}
            </AnimatePresence>
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
            aria-label="Attach photos"
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-xl
                       border border-gray-800 text-gray-400 hover:text-gray-200
                       hover:border-gray-600 disabled:opacity-40 transition-colors"
          >
            📎
          </button>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              pendingImages.length > 0 ? "Add a caption (optional)…" : "Type a message…"
            }
            disabled={loading}
            className="flex-1 bg-card border border-border rounded-xl px-4 py-2.5
                       text-sm placeholder-gray-600 focus:outline-none
                       focus:ring-2 focus:ring-accent/50 focus:border-accent
                       disabled:opacity-50 transition-all"
          />
          <button
            type="submit"
            disabled={loading || (!input.trim() && pendingImages.length === 0)}
            className="bg-accent hover:bg-accent/90 disabled:opacity-40 transition-colors
                       text-white text-sm font-semibold rounded-xl px-4 py-2.5 shrink-0"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
