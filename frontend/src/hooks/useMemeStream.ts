"use client";

import { useState } from "react";
import { sendChatImageStream, sendChatStream } from "@/lib/api";
import type { MemeItem, SSEEvent } from "@/types";

interface ThinkingState {
  message: string;
}

export interface PlanState {
  situations: string[];
  total: number;
  doneIndices: Set<number>;
}

export interface MemeStreamResult {
  memes: MemeItem[];
  plainReply: string | null;
}

/**
 * Owns the transient state of one SSE submission (thinking/error/loading/
 * plan/conversationId) and the shared accumulation logic: every "done"
 * event's meme is collected locally across the whole stream (not pushed
 * into any list one at a time), and the accumulated result is returned once
 * the stream ends. Does NOT own a message/feed list — Chat groups a
 * submission's memes into one chat bubble, Lore appends them as separate
 * cards to a flat feed; that's presentation-specific and stays with the
 * caller. Extracted verbatim from ChatWindow's original submit() so Chat's
 * behavior is provably unchanged.
 */
export function useMemeStream() {
  const [loading, setLoading] = useState(false);
  const [thinking, setThinking] = useState<ThinkingState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<PlanState | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();

  function handleEvent(event: SSEEvent, collected: MemeItem[], onPlainReply: (s: string) => void) {
    if (event.type === "plan") {
      setPlan({ situations: event.situations, total: event.total, doneIndices: new Set() });
    } else if (event.type === "thinking") {
      const progress =
        event.total && event.total > 1 ? ` (${(event.index ?? 0) + 1}/${event.total})` : "";
      setThinking({ message: `${event.message}${progress}` });
    } else if (event.type === "done") {
      setConversationId(event.conversation_id);
      if (event.index !== undefined) {
        setPlan((prev) =>
          prev ? { ...prev, doneIndices: new Set(prev.doneIndices).add(event.index as number) } : prev,
        );
      }
      if (event.message.meme_url) {
        collected.push({
          url: event.message.meme_url,
          templateId: event.template_used,
          situationText: event.message.content,
          memeId: event.message.meme_id,
        });
      } else {
        // A graceful text-only reply (e.g. vision unavailable) rather than
        // a meme — still worth surfacing, just not as a meme card.
        onPlainReply(event.message.content);
      }
    } else if (event.type === "error") {
      setError(event.message);
    }
    // batch_done needs no handling here — finalization runs once the
    // stream itself ends, which covers every exit path (a full multi-meme
    // batch, an early single-error abort, or a graceful degrade reply)
    // the same way, regardless of caller.
  }

  async function run(
    send: (onEvent: (event: SSEEvent) => void) => Promise<void>,
  ): Promise<MemeStreamResult> {
    setLoading(true);
    setError(null);
    setPlan(null);
    setThinking({ message: "Reading your vibe…" });

    const collected: MemeItem[] = [];
    let plainReply: string | null = null;

    try {
      await send((event) =>
        handleEvent(event, collected, (s) => {
          plainReply = s;
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
      setThinking(null);
    }

    return { memes: collected, plainReply };
  }

  async function submitText(message: string, memeCount?: number): Promise<MemeStreamResult> {
    return run((onEvent) => sendChatStream(message, conversationId, onEvent, memeCount));
  }

  async function submitImages(
    files: File[],
    message?: string,
    memeCount?: number,
  ): Promise<MemeStreamResult> {
    return run((onEvent) => sendChatImageStream(files, { message, conversationId, memeCount }, onEvent));
  }

  return { loading, thinking, error, plan, conversationId, submitText, submitImages };
}
