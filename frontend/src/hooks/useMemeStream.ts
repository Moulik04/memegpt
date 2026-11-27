"use client";

import { useState } from "react";
import { ApiError, sendImageStream, sendStream, type Surface } from "@/lib/api";
import { templateLabel } from "@/lib/utils";
import type { LoreTextOptions, MemeItem, NoticeReason, SSEEvent, UploadErrorCode } from "@/types";

interface ThinkingState {
  message: string;
}

export type StageKey = "looking" | "analyzing" | "rendering";

/** One step of a submission, worded for the person waiting on it. The last
 * one in the list is current; the ones before it are finished. Steps that
 * haven't started are never listed. */
export interface ThinkingStage {
  key: StageKey;
  label: string;
}

const STAGE_ORDER: StageKey[] = ["looking", "analyzing", "rendering"];

function stageLabel(key: StageKey, photos: number, templateId?: string): string {
  if (key === "looking") return photos > 1 ? "Looking at the photos" : "Looking at the photo";
  if (key === "analyzing") return "Reading the message";
  return templateId ? `Captioning ${templateLabel(templateId)}` : "Captioning the photo";
}

/** Moves the list to `key`: drops anything at or after it (a later meme in
 * the same batch starts its own read and caption over), then appends it. */
function advance(stages: ThinkingStage[], next: ThinkingStage): ThinkingStage[] {
  const at = STAGE_ORDER.indexOf(next.key);
  return [...stages.filter((s) => STAGE_ORDER.indexOf(s.key) < at), next];
}

export interface PlanState {
  situations: string[];
  total: number;
  doneIndices: Set<number>;
  // Parallel to situations: the moment an entry is another take on, or null.
  takeOf: (number | null)[];
  // Parallel to situations: the pasted line numbers each drew on, or null.
  // Absent when the backend sent none (an older backend).
  sourceLines?: (number[] | null)[];
  // The meme each finished entry made, by index, as it lands.
  memes: Record<number, MemeItem>;
  // Entries the backend said it could not make.
  failedIndices: Set<number>;
  // The entry being worked on now, from the latest thinking event.
  activeIndex: number | null;
  // True once the stream has ended, however it ended. An entry that is
  // still not done at that point is never going to be.
  finished: boolean;
}

export interface StreamFailure {
  message: string;
  reason: NoticeReason | null;
  code: UploadErrorCode | null;
  /** Another take found no template it may use. */
  noFreshTemplate?: boolean;
  /** The plan entry it belongs to, when it is one entry's error. */
  index?: number;
}

export interface MemeStreamResult {
  memes: MemeItem[];
  plainReply: string | null;
  /** The submission's error, if it ended in one. The same as the hook's
   * error state, returned too so a caller can keep it with its turn. */
  failure: StreamFailure | null;
  /** The plan as it stood when the stream ended, if one was sent. */
  plan: PlanState | null;
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
export function useMemeStream(surface: Surface, conversationRowId?: string) {
  const [loading, setLoading] = useState(false);
  const [thinking, setThinking] = useState<ThinkingState | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Set with `error` when the backend said which expected case it was, so
  // the caller can show the budget meme for "site_budget".
  const [errorReason, setErrorReason] = useState<NoticeReason | null>(null);
  // Set with `error` on an upload refusal, so the caller can word it.
  const [errorCode, setErrorCode] = useState<UploadErrorCode | null>(null);
  const [stages, setStages] = useState<ThinkingStage[]>([]);
  const [plan, setPlan] = useState<PlanState | null>(null);
  const [conversationId, setConversationId] = useState<string | undefined>();

  function handleEvent(
    event: SSEEvent,
    collected: MemeItem[],
    onPlainReply: (s: string) => void,
    photos: number,
    onFailure: (f: StreamFailure) => void,
    current: { plan: PlanState | null },
  ) {
    // The plan is kept here as well as in state, so run() can return it as
    // it stood when the stream ended.
    const updatePlan = (change: (p: PlanState) => PlanState) => {
      if (!current.plan) return;
      current.plan = change(current.plan);
      setPlan(current.plan);
    };
    if (event.type === "plan") {
      current.plan = {
        situations: event.situations,
        total: event.total,
        doneIndices: new Set(),
        takeOf: event.take_of ?? event.situations.map(() => null),
        sourceLines: event.source_lines,
        memes: {},
        failedIndices: new Set(),
        activeIndex: null,
        finished: false,
      };
      setPlan(current.plan);
    } else if (event.type === "thinking") {
      if (event.index !== undefined) updatePlan((p) => ({ ...p, activeIndex: event.index as number }));
      const progress =
        event.total && event.total > 1 ? ` (${(event.index ?? 0) + 1}/${event.total})` : "";
      setThinking({ message: `${event.message}${progress}` });
      // Keyed off `stage`, not the backend's own text, which today's site
      // still prints as is.
      const key = event.stage as StageKey;
      if (STAGE_ORDER.includes(key)) {
        setStages((prev) => advance(prev, { key, label: stageLabel(key, photos, event.template_id) }));
      }
    } else if (event.type === "done") {
      setConversationId(event.conversation_id);
      const meme: MemeItem | null = event.message.meme_url
        ? {
            url: event.message.meme_url,
            templateId: event.template_used,
            situationText: event.message.content,
            memeId: event.message.meme_id,
            takeOf: event.take_of,
          }
        : null;
      if (event.index !== undefined) {
        const index = event.index;
        updatePlan((p) => ({
          ...p,
          doneIndices: new Set(p.doneIndices).add(index),
          memes: meme ? { ...p.memes, [index]: meme } : p.memes,
        }));
      }
      if (meme) {
        collected.push(meme);
      } else {
        // A graceful text-only reply (e.g. vision unavailable) rather than
        // a meme — still worth surfacing, just not as a meme card.
        onPlainReply(event.message.content);
      }
    } else if (event.type === "error") {
      const noFreshTemplate = event.code === "no_fresh_template";
      const code = event.code && !noFreshTemplate ? (event.code as UploadErrorCode) : null;
      if (event.index !== undefined) {
        const index = event.index;
        updatePlan((p) => ({ ...p, failedIndices: new Set(p.failedIndices).add(index) }));
      }
      setError(event.message);
      setErrorReason(event.reason ?? null);
      setErrorCode(code);
      onFailure({
        message: event.message,
        reason: event.reason ?? null,
        code,
        noFreshTemplate,
        index: event.index,
      });
    }
    // batch_done needs no handling here — finalization runs once the
    // stream itself ends, which covers every exit path (a full multi-meme
    // batch, an early single-error abort, or a graceful degrade reply)
    // the same way, regardless of caller.
  }

  async function run(
    send: (onEvent: (event: SSEEvent) => void) => Promise<void>,
    photos = 0,
  ): Promise<MemeStreamResult> {
    setLoading(true);
    setError(null);
    setErrorReason(null);
    setErrorCode(null);
    setPlan(null);
    setThinking({ message: "Reading your vibe…" });
    // The first step is known before the backend says anything.
    const first: StageKey = photos > 0 ? "looking" : "analyzing";
    setStages([{ key: first, label: stageLabel(first, photos) }]);

    const collected: MemeItem[] = [];
    let plainReply: string | null = null;
    let failure: StreamFailure | null = null;
    const current: { plan: PlanState | null } = { plan: null };

    try {
      await send((event) =>
        handleEvent(
          event,
          collected,
          (s) => {
            plainReply = s;
          },
          photos,
          (f) => {
            failure = f;
          },
          current,
        ),
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      const reason = err instanceof ApiError ? (err.reason ?? null) : null;
      setError(message);
      setErrorReason(reason);
      failure = { message, reason, code: null };
    } finally {
      setLoading(false);
      setThinking(null);
      setStages([]);
      if (current.plan) current.plan = { ...current.plan, finished: true, activeIndex: null };
      setPlan(current.plan);
    }

    return { memes: collected, plainReply, failure, plan: current.plan };
  }

  async function submitText(
    message: string,
    memeCount?: number,
    rememberLore?: boolean,
    // Overrides the conversationRowId this hook was called with — needed
    // when the caller just created a conversation in the same submit
    // handler (e.g. auto-create-on-first-message): conversationRowId is a
    // plain closed-over param, so setConversationRowId() followed
    // immediately by submitText() in one handler would otherwise still
    // see the OLD value, since React state updates don't apply until the
    // next render.
    conversationRowIdOverride?: string,
    lore?: LoreTextOptions,
  ): Promise<MemeStreamResult> {
    return run((onEvent) =>
      sendStream(
        surface,
        message,
        conversationId,
        onEvent,
        memeCount,
        rememberLore,
        conversationRowIdOverride ?? conversationRowId,
        lore,
      ),
    );
  }

  async function submitImages(
    files: File[],
    message?: string,
    memeCount?: number,
    rememberLore?: boolean,
    conversationRowIdOverride?: string,
  ): Promise<MemeStreamResult> {
    return run((onEvent) =>
      sendImageStream(
        surface,
        files,
        {
          message,
          conversationId,
          memeCount,
          rememberLore,
          conversationRowId: conversationRowIdOverride ?? conversationRowId,
        },
        onEvent,
      ),
      files.length,
    );
  }

  return {
    loading,
    thinking,
    stages,
    error,
    errorReason,
    errorCode,
    plan,
    conversationId,
    submitText,
    submitImages,
  };
}
