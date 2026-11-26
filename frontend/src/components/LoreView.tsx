"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from "motion/react";
import { FAST_OUT, FAST_SETTLE, INSTANT, SETTLE } from "@/lib/motion";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { createConversation, getConversationMessages, memeImageUrl, postFeedback } from "@/lib/api";
import { useMemeStream, type PlanState, type StreamFailure } from "@/hooks/useMemeStream";
import { useConversation } from "@/lib/ConversationContext";
import { useAuth } from "@/hooks/useAuth";
import {
  MAX_IMAGE_BYTES,
  MAX_IMAGES_PER_MESSAGE,
  PICK_TOO_LARGE,
  PICK_TOO_MANY,
  PICK_UNSUPPORTED,
  noticeFor,
  type Notice,
} from "@/lib/notices";
import { allSupportedImages } from "@/lib/imageFormat";
import {
  isOverCut,
  linesForEntry,
  moreMessagesLabel,
  previewLines,
  quoteLines,
  splitSpeaker,
  type QuotedLine,
} from "@/lib/sourceLines";
import { MemeDisplay } from "./MemeDisplay";
import { MEME_ACTION, MemeActions } from "./MemeActions";
import BudgetNotice from "./BudgetNotice";
import type { MemeItem, PersistedMessage } from "@/types";

const BACKEND_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** Copy deck, section 7.4. */
const COUNT_OPTIONS: { label: string; value: number | undefined }[] = [
  { label: "Auto", value: undefined },
  ...[1, 2, 3, 4, 5].map((n) => ({ label: String(n), value: n })),
];
const RETENTION_SIGNED_OUT = "Your text and original photos aren't saved. Only the memes MemeGPT makes are.";
const RETENTION_SIGNED_IN =
  "You're signed in, so this is saved to your history, usually as a short summary of each moment. Original photos aren't kept.";
const REMEMBER_ON =
  "Remember lore is on. Short recurring names and jokes are kept for future memes until you use Forget me.";
const REMEMBER_OFF = "Remember lore is off. Turn it on to carry recurring names and jokes into future memes.";
const OVER_CUT = "Only the first 20,000 characters are used.";
const FAILED_MOMENT = "This one didn't come out.";
const UP_NEXT = "Up next";
const NO_FRESH_TEMPLATE = "MemeGPT couldn't find a different template for this one.";
const ANOTHER_TAKE = "Another take";

/** Tall memes pair side by side; anything less tall than this gets a row. */
const TALL_RATIO = 1.1;

function base64ToFile(dataBase64: string, filename: string, contentType: string): File {
  const byteChars = atob(dataBase64);
  const bytes = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i);
  return new File([bytes], filename, { type: contentType });
}

// Counts moments and extra takes separately, so the status never calls a
// second take a moment, and adds the real total only if Lore finished short.
function planHeading(plan: PlanState): string {
  const takes = plan.takeOf.filter((t) => t !== null).length;
  const moments = plan.total - takes;
  let heading = `Found ${moments} moment${moments === 1 ? "" : "s"} worth memeing`;
  if (takes > 0) heading += `, plus ${takes} more take${takes === 1 ? "" : "s"}`;
  const made = plan.doneIndices.size;
  if (plan.finished && made < plan.total) heading += `. ${made} of ${plan.total} memes made`;
  return heading;
}

interface PendingImage {
  file: File;
  previewUrl: string;
}

/** One paste or set of screenshots and everything that came back for it. */
interface Submission {
  id: string;
  /** The exact string sent, which source lines number. Empty for
   * screenshots only and for a chat reopened from history. */
  sent: string;
  images?: string[];
  plan: PlanState | null;
  /** The memes, for a submission with no plan (history, older backend). */
  memes: MemeItem[];
  reply?: string;
  notice?: Notice & { budget: boolean };
  pending: boolean;
}

type RowState = "done" | "active" | "waiting" | "failed";

/** One moment (or take) of a submission, in source order. */
interface Row {
  key: string;
  index: number;
  /** The moment it is another take on, if it is one. */
  takeOf: number | null;
  summary: string;
  quote: QuotedLine[] | null;
  meme: MemeItem | null;
  state: RowState;
}

function rowsFor(sub: Submission): Row[] {
  const plan = sub.plan;
  if (!plan) {
    return sub.memes.map((meme, i) => ({
      key: `${sub.id}-${i}`,
      index: i,
      takeOf: meme.takeOf ?? null,
      summary: meme.situationText,
      quote: null,
      meme,
      state: "done" as const,
    }));
  }
  return plan.situations.map((summary, i) => {
    const meme = plan.memes[i] ?? null;
    const failed = plan.failedIndices.has(i) || (plan.finished && !plan.doneIndices.has(i));
    const state: RowState = meme
      ? "done"
      : failed
        ? "failed"
        : plan.activeIndex === i
          ? "active"
          : "waiting";
    return {
      key: `${sub.id}-${i}`,
      index: i,
      takeOf: plan.takeOf[i] ?? null,
      summary,
      quote: sub.sent ? quoteLines(sub.sent, linesForEntry(plan.sourceLines, plan.takeOf, i)) : null,
      meme,
      state,
    };
  });
}

let submissionCounter = 0;
const newSubmissionId = () => `lore-${Date.now()}-${submissionCounter++}`;

// A reopened Lore chat stores one summary per moment (as the user row) and
// the meme made from it. Quotes are never stored, so it shows summaries.
function submissionFromPersisted(rows: PersistedMessage[]): Submission[] {
  const memes: MemeItem[] = [];
  let reply: string | undefined;
  for (const row of rows) {
    if (row.role !== "assistant") continue;
    if (row.meme_url) memes.push({ url: row.meme_url, situationText: row.content, memeId: row.meme_id ?? undefined });
    else if (row.content) reply = row.content;
  }
  if (memes.length === 0 && !reply) return [];
  return [{ id: "saved", sent: "", plan: null, memes, reply, pending: false }];
}

function failureNotice(failure: StreamFailure, sentPhotos: boolean): Submission["notice"] {
  return {
    ...noticeFor(failure.message, { code: failure.code, hasReason: !!failure.reason, sentPhotos }),
    budget: failure.reason === "site_budget",
  };
}

function preload(url: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = () => resolve();
    img.src = url.startsWith("http") ? url : memeImageUrl(url);
  });
}

type Rating = "up" | "down";

/** What another take on a row has done: the meme it now shows, the
 * templates that row has used, and a note when it couldn't make one. */
interface TakeState {
  meme?: MemeItem;
  used: string[];
  note?: string;
}


/**
 * Lore: paste a whole group chat or drop in screenshots, get one meme per
 * moment back, in chat order, each credited to the lines it came from.
 */
export function LoreView() {
  const [text, setText] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [memeCount, setMemeCount] = useState<number | undefined>(undefined);
  // Off by default and kept across submissions: it means "remember this
  // group", not "remember this one paste".
  const [rememberLore, setRememberLore] = useState(false);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);
  const [ratings, setRatings] = useState<Record<string, Rating>>({});
  const [takes, setTakes] = useState<Record<string, TakeState>>({});
  const [taking, setTaking] = useState<string | null>(null);
  const [sizes, setSizes] = useState<Record<string, number>>({});
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const focusPaste = useRef(false);
  const focusExpand = useRef(false);
  const expandRef = useRef<HTMLButtonElement>(null);
  const pendingImagesRef = useRef<PendingImage[]>([]);
  const dragDepth = useRef(0);

  const { user } = useAuth();
  const { conversationRowId, setConversationRowId, bumpRefresh } = useConversation();
  const { loading, stages, plan, conversationId, submitText, submitImages } = useMemeStream("lore", conversationRowId);
  // Another take runs as its own request, so the submission's plan stays.
  const take = useMemeStream("lore", conversationRowId);
  const router = useRouter();
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!conversationRowId) {
      setSubmissions([]);
      return;
    }
    let cancelled = false;
    getConversationMessages(conversationRowId)
      .then((rows) => {
        if (!cancelled) setSubmissions(submissionFromPersisted(rows));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [conversationRowId]);

  useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  useEffect(
    () => () => {
      pendingImagesRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    },
    [],
  );

  // Focus follows the swap between the field and its preview, so a
  // keyboard user never loses their place.
  useEffect(() => {
    if (!collapsed && focusPaste.current) {
      focusPaste.current = false;
      textareaRef.current?.focus();
    }
    if (collapsed && focusExpand.current) {
      focusExpand.current = false;
      expandRef.current?.focus();
    }
  }, [collapsed]);

  // A share-target handoff (?intake=<token>) fills the composer, never
  // sends, and the token is dropped from the address so a refresh doesn't
  // retry a single-use token.
  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("intake");
    if (!token) return;
    (async () => {
      try {
        const res = await fetch(`${BACKEND_BASE}/share-intake/${token}/`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.text) {
          setText((prev) => prev || data.text);
          if (previewLines(data.text).more > 0) setCollapsed(true);
        }
        const newImages: PendingImage[] = (data.images ?? [])
          .slice(0, MAX_IMAGES_PER_MESSAGE)
          .map((img: { filename: string; content_type: string; data_base64: string }) => {
            const file = base64ToFile(img.data_base64, img.filename, img.content_type);
            return { file, previewUrl: URL.createObjectURL(file) };
          });
        if (newImages.length > 0) setPendingImages((prev) => [...prev, ...newImages].slice(0, MAX_IMAGES_PER_MESSAGE));
      } catch {
        // Worst case the visitor shares again or attaches by hand.
      } finally {
        router.replace("/lore");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFeedback = useCallback(
    async (meme: MemeItem, rating: Rating) => {
      setRatings((prev) => ({ ...prev, [meme.url]: rating }));
      await postFeedback({
        conversation_id: conversationId,
        template_id: meme.templateId || "",
        rating,
        meme_id: meme.memeId,
      }).catch(() => {});
    },
    [conversationId],
  );

  const handleSize = useCallback((url: string, width: number, height: number) => {
    setSizes((prev) => (prev[url] ? prev : { ...prev, [url]: height / width }));
  }, []);

  // A pick that breaks a limit is turned away whole; images already
  // attached stay.
  async function addFiles(files: File[]) {
    if (files.length === 0) return;
    if (files.some((f) => f.size > MAX_IMAGE_BYTES)) {
      setPickError(PICK_TOO_LARGE);
      return;
    }
    if (pendingImages.length + files.length > MAX_IMAGES_PER_MESSAGE) {
      setPickError(PICK_TOO_MANY);
      return;
    }
    if (!(await allSupportedImages(files))) {
      setPickError(PICK_UNSUPPORTED);
      return;
    }
    setPendingImages((prev) => [...prev, ...files.map((file) => ({ file, previewUrl: URL.createObjectURL(file) }))]);
    setPickError(null);
  }

  function removePendingImage(index: number) {
    setPendingImages((prev) => {
      const target = prev[index];
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
    setPickError(null);
  }

  function handleTextChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 400)}px`;
  }

  function expandPaste() {
    focusPaste.current = true;
    setCollapsed(false);
  }

  function handleDragEnter(e: React.DragEvent) {
    if (!Array.from(e.dataTransfer.types).includes("Files")) return;
    e.preventDefault();
    dragDepth.current += 1;
    setDragActive(true);
  }

  function handleDragLeave() {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    if (loading) return;
    addFiles(Array.from(e.dataTransfer.files ?? []).filter((f) => f.type.startsWith("image/")));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Trimmed before sending, and the trimmed string is what lines number.
    const sent = text.trim();
    const images = pendingImages;
    if ((!sent && images.length === 0) || loading) return;

    const id = newSubmissionId();
    setSubmissions((prev) => [
      {
        id,
        sent: images.length > 0 ? "" : sent,
        images: images.length > 0 ? images.map((p) => p.previewUrl) : undefined,
        plan: null,
        memes: [],
        pending: true,
      },
      ...prev,
    ]);
    setText("");
    setCollapsed(false);
    // The preview URLs now belong to the sent submission.
    setPendingImages([]);
    setPickError(null);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    requestAnimationFrame(() =>
      resultsRef.current?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" }),
    );

    let activeConversationRowId = conversationRowId;
    if (user && !activeConversationRowId) {
      const created = await createConversation("lore").catch(() => null);
      if (created) {
        activeConversationRowId = created.id;
        setConversationRowId(created.id);
      }
    }

    const result =
      images.length > 0
        ? await submitImages(
            images.map((p) => p.file),
            sent || undefined,
            memeCount,
            rememberLore,
            activeConversationRowId,
          )
        : await submitText(sent, memeCount, rememberLore, activeConversationRowId);

    setSubmissions((prev) =>
      prev.map((s) =>
        s.id === id
          ? {
              ...s,
              plan: result.plan,
              memes: result.memes,
              reply: result.memes.length === 0 ? (result.plainReply ?? undefined) : undefined,
              notice:
                result.memes.length === 0 && result.failure
                  ? failureNotice(result.failure, images.length > 0)
                  : undefined,
              pending: false,
            }
          : s,
      ),
    );
    if (activeConversationRowId) bumpRefresh();
  }

  async function anotherTake(sub: Submission, row: Row) {
    const current = takes[row.key]?.meme ?? row.meme;
    if (!current || taking) return;
    const moment = row.takeOf ?? row.index;
    // The summary is what the first pick saw, so the take stays on the
    // same moment, and history keeps storing summaries, not pasted lines.
    const summary = sub.plan?.situations[moment] ?? row.summary;
    // Every template already shown for this moment, in any of its rows.
    const used = new Set(takes[row.key]?.used ?? []);
    for (const r of rowsFor(sub)) {
      if ((r.takeOf ?? r.index) !== moment) continue;
      const shown = takes[r.key]?.meme ?? r.meme;
      if (shown?.templateId) used.add(shown.templateId);
      for (const t of takes[r.key]?.used ?? []) used.add(t);
    }

    setTaking(row.key);
    setTakes((prev) => ({ ...prev, [row.key]: { ...prev[row.key], used: [...used], note: undefined } }));
    const result = await take.submitText(summary, 1, false, conversationRowId, {
      excludeTemplates: [...used],
      includeSourceLines: false,
    });
    const meme = result.memes[0];
    if (meme) {
      // Swapped only once the new image is ready, so the frame never blanks.
      await preload(meme.url);
      setTakes((prev) => ({
        ...prev,
        [row.key]: {
          meme: { ...meme, takeOf: row.takeOf ?? undefined },
          used: meme.templateId ? [...used, meme.templateId] : [...used],
        },
      }));
    } else {
      const f = result.failure;
      const note = f?.noFreshTemplate
        ? NO_FRESH_TEMPLATE
        : f
          ? [noticeFor(f.message, { code: f.code, hasReason: !!f.reason, sentPhotos: false })]
              .map((n) => (n.heading ? `${n.heading} ${n.text}` : n.text))[0]
          : NO_FRESH_TEMPLATE;
      setTakes((prev) => ({ ...prev, [row.key]: { ...prev[row.key], used: [...used], note } }));
    }
    setTaking(null);
    if (conversationRowId) bumpRefresh();
  }

  const preview = previewLines(text);
  const showPreview = collapsed && preview.more > 0;
  const canSend = !loading && (text.trim().length > 0 || pendingImages.length > 0);
  const currentStage = stages.length > 0 ? stages[stages.length - 1].label : null;

  return (
    <MotionConfig reducedMotion="user" transition={SETTLE}>
      <main className="flex-1 overflow-y-auto chat-scroll">
        <div className="mx-auto max-w-6xl px-4 md:px-8 pt-6 md:pt-8 pb-12">
          <h1 className="sr-only">Lore</h1>

          <form
            onSubmit={handleSubmit}
            onDragEnter={handleDragEnter}
            onDragOver={(e) => {
              if (Array.from(e.dataTransfer.types).includes("Files")) e.preventDefault();
            }}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className="relative flex flex-col gap-4 lg:max-w-3xl"
          >
            {dragActive && (
              <div
                className="absolute inset-0 z-10 flex items-center justify-center bg-background/95
                           border-2 border-dashed border-foreground pointer-events-none"
              >
                <p className="font-display text-3xl md:text-4xl text-foreground">Drop screenshots here</p>
              </div>
            )}

            {showPreview ? (
              <div className="border border-input rounded-sm px-3 py-3">
                <TranscriptLines lines={preview.lines} />
                <button
                  ref={expandRef}
                  type="button"
                  onClick={expandPaste}
                  aria-expanded={false}
                  aria-controls="lore-paste"
                  className="mt-1 min-h-11 text-base font-medium text-foreground underline decoration-brand
                             decoration-2 underline-offset-4 hover:decoration-[3px]"
                >
                  {moreMessagesLabel(preview.more)}
                </button>
              </div>
            ) : (
              <textarea
                id="lore-paste"
                ref={textareaRef}
                value={text}
                onChange={handleTextChange}
                onPaste={() =>
                  // A long paste folds to its first lines once it has landed.
                  // Not on blur: the swap would move Drop the lore out from
                  // under a click on it.
                  requestAnimationFrame(() => {
                    if (previewLines(textareaRef.current?.value ?? "").more > 0) {
                      focusExpand.current = true;
                      setCollapsed(true);
                    }
                  })
                }
                aria-label="Paste the group chat"
                placeholder="Paste the group chat"
                disabled={loading}
                rows={6}
                className="w-full min-h-40 px-3 py-3 text-base leading-relaxed bg-background border border-input
                           rounded-sm resize-none placeholder:text-muted-foreground disabled:opacity-60"
              />
            )}

            {isOverCut(text.trim()) && <p className="text-base text-muted-foreground">{OVER_CUT}</p>}

            <ul aria-label="Attached screenshots" className="flex flex-wrap gap-x-3 gap-y-1 empty:hidden">
              <AnimatePresence initial={false}>
                {pendingImages.map((p, i) => (
                  <motion.li
                    key={p.previewUrl}
                    initial={reduceMotion ? false : { opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.9 }}
                    transition={reduceMotion ? INSTANT : FAST_SETTLE}
                    className="flex items-center gap-1"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element -- local preview */}
                    <img
                      src={p.previewUrl}
                      alt={`Attached screenshot ${i + 1}`}
                      className="w-12 h-12 object-cover border border-border"
                    />
                    <button
                      type="button"
                      onClick={() => removePendingImage(i)}
                      aria-label={`Remove screenshot ${i + 1}`}
                      className="min-h-11 px-2 text-base text-muted-foreground hover:text-foreground
                                 underline underline-offset-4 transition-colors duration-[var(--duration-fast)]"
                    >
                      Remove
                    </button>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>

            <div className="flex flex-col md:flex-row md:items-center gap-3 md:gap-6">
              <fieldset className="flex items-center">
                <legend className="sr-only">Number of memes</legend>
                <div className="flex">
                  {COUNT_OPTIONS.map((option) => (
                    <label key={option.label} className="relative -ml-px first:ml-0">
                      <input
                        type="radio"
                        name="lore-count"
                        checked={memeCount === option.value}
                        onChange={() => setMemeCount(option.value)}
                        disabled={loading}
                        className="peer sr-only"
                      />
                      <span
                        className="flex items-center justify-center min-h-11 min-w-11 px-3 border border-input
                                   text-base font-medium text-foreground cursor-pointer select-none
                                   peer-checked:bg-foreground peer-checked:text-background peer-checked:border-foreground
                                   peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2
                                   peer-focus-visible:outline-focus-ring peer-disabled:opacity-60
                                   transition-colors duration-[var(--duration-fast)]"
                      >
                        {option.label}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <button
                type="button"
                role="switch"
                aria-checked={rememberLore}
                aria-describedby="lore-remember-help"
                onClick={() => setRememberLore((v) => !v)}
                disabled={loading}
                className="self-start md:self-auto min-h-11 inline-flex items-center gap-3 text-base font-medium
                           text-foreground disabled:opacity-60"
              >
                <span
                  aria-hidden="true"
                  className={`relative inline-flex h-6 w-11 shrink-0 rounded-sm border transition-colors
                              duration-[var(--duration-fast)] ${
                                rememberLore ? "bg-foreground border-foreground" : "bg-muted border-input"
                              }`}
                >
                  <span
                    className={`absolute top-[3px] h-4 w-4 rounded-[2px] transition-transform
                                duration-[var(--duration-fast)] motion-reduce:transition-none ${
                                  rememberLore ? "translate-x-[23px] bg-background" : "translate-x-[3px] bg-muted-foreground"
                                }`}
                  />
                </span>
                Remember lore
              </button>
            </div>

            <div className="flex gap-2">
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
                className="min-h-12 px-5 border border-input rounded-sm text-base font-medium text-foreground
                           hover:bg-muted disabled:opacity-40 transition-colors duration-[var(--duration-fast)]"
              >
                Photo
              </button>
              <button
                type="submit"
                disabled={!canSend}
                className="flex-1 md:flex-none min-h-12 px-6 rounded-sm bg-primary text-primary-foreground
                           text-base font-semibold hover:bg-primary/85 disabled:opacity-40
                           transition-colors duration-[var(--duration-fast)]"
              >
                Drop the lore
              </button>
            </div>

            {pickError && (
              <p role="alert" className="text-base text-foreground border-l-2 border-brand pl-3">
                {pickError}
              </p>
            )}

            <div className="flex flex-col gap-1 text-sm text-muted-foreground max-w-prose">
              <p>{user ? RETENTION_SIGNED_IN : RETENTION_SIGNED_OUT}</p>
              <p id="lore-remember-help">{rememberLore ? REMEMBER_ON : REMEMBER_OFF}</p>
              <p>
                <Link
                  href="/privacy"
                  className="inline-flex min-h-11 items-center text-base text-foreground underline underline-offset-4"
                >
                  Privacy
                </Link>
              </p>
            </div>
          </form>

          <div ref={resultsRef} className="scroll-mt-4 flex flex-col">
            {submissions.map((sub, i) => (
              <SubmissionBlock
                key={sub.id}
                sub={sub}
                latest={i === 0}
                livePlan={sub.pending ? plan : null}
                stage={sub.pending ? currentStage : null}
                takes={takes}
                taking={taking}
                takeStage={take.stages.length > 0 ? take.stages[take.stages.length - 1].label : null}
                ratings={ratings}
                sizes={sizes}
                onSize={handleSize}
                onFeedback={handleFeedback}
                onAnotherTake={anotherTake}
              />
            ))}
          </div>
        </div>
      </main>
    </MotionConfig>
  );
}

function TranscriptLines({ lines, className = "" }: { lines: QuotedLine[]; className?: string }) {
  return (
    <div className={`flex flex-col gap-0.5 text-base leading-snug text-foreground ${className}`}>
      {lines.map((line) => (
        <p key={line.number}>
          {line.speaker && <span className="font-bold">{line.speaker}: </span>}
          {line.text}
        </p>
      ))}
    </div>
  );
}

/** The sent paste, collapsed to three lines with the rest a tap away. */
function SentTranscript({ sent }: { sent: string }) {
  const [open, setOpen] = useState(false);
  const reduceMotion = useReducedMotion();
  const { lines, more } = previewLines(sent);
  const all = sent
    .split("\n")
    .map((line, i) => ({ number: i + 1, ...splitSpeaker(line) }))
    .filter((l) => l.text.trim() !== "");
  return (
    <div className="border-l-2 border-border pl-3">
      <TranscriptLines lines={lines} className="text-muted-foreground" />
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={reduceMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={reduceMotion ? INSTANT : FAST_OUT}
            className="overflow-hidden"
          >
            <TranscriptLines lines={all.slice(lines.length)} className="text-muted-foreground" />
          </motion.div>
        )}
      </AnimatePresence>
      {more > 0 && !open && (
        <button
          type="button"
          aria-expanded={false}
          onClick={() => setOpen(true)}
          className="min-h-11 text-base font-medium text-foreground underline decoration-brand decoration-2
                     underline-offset-4"
        >
          {moreMessagesLabel(more)}
        </button>
      )}
    </div>
  );
}

interface BlockProps {
  sub: Submission;
  latest: boolean;
  livePlan: PlanState | null;
  stage: string | null;
  takes: Record<string, TakeState>;
  taking: string | null;
  takeStage: string | null;
  ratings: Record<string, Rating>;
  sizes: Record<string, number>;
  onSize: (url: string, width: number, height: number) => void;
  onFeedback: (meme: MemeItem, rating: Rating) => void;
  onAnotherTake: (sub: Submission, row: Row) => void;
}

function SubmissionBlock(props: BlockProps) {
  const { sub, latest, livePlan, stage } = props;
  const shown: Submission = sub.pending ? { ...sub, plan: livePlan } : sub;
  const rows = rowsFor(shown);
  const heading = shown.plan ? planHeading(shown.plan) : null;

  return (
    <section
      aria-label={latest ? "Latest lore" : "Earlier lore"}
      className={`pt-8 mt-8 md:mt-10 ${latest ? "border-t-2 border-foreground" : "border-t border-border"}`}
    >
      {sub.sent && <SentTranscript sent={sub.sent} />}
      {sub.images && sub.images.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {sub.images.map((src, i) => (
            // eslint-disable-next-line @next/next/no-img-element -- local preview
            <img key={src} src={src} alt={`Sent screenshot ${i + 1}`} className="w-12 h-12 object-cover border border-border" />
          ))}
        </div>
      )}

      <div aria-live="polite">
        {heading && (
          <h2 className="mt-5 font-display text-3xl md:text-4xl leading-tight text-foreground">{heading}</h2>
        )}
        {sub.pending && !shown.plan && stage && (
          <p className="mt-5 flex items-center gap-2 text-base font-medium text-foreground">
            <Spinner />
            {stage}
          </p>
        )}
      </div>

      {sub.notice &&
        (sub.notice.budget ? (
          <div className="mt-5">
            <BudgetNotice message={sub.notice.text} maxHeightClassName="max-h-[45vh]" />
          </div>
        ) : (
          <div role="alert" className="mt-5 text-base text-foreground border-l-2 border-brand pl-3 max-w-prose">
            {sub.notice.heading && <p className="font-semibold">{sub.notice.heading}</p>}
            <p>{sub.notice.text}</p>
          </div>
        ))}

      {sub.reply && <p className="mt-5 text-lg text-foreground max-w-prose">{sub.reply}</p>}

      {sub.pending ? (
        <ProgressRows {...props} rows={rows} />
      ) : (
        <ResultRows {...props} rows={rows} />
      )}
    </section>
  );
}

function Spinner() {
  return (
    <>
      <LoaderCircle
        size={18}
        strokeWidth={2.25}
        aria-hidden="true"
        className="shrink-0 animate-spin motion-reduce:hidden"
      />
      {/* Reduced motion: a static marker in the spinner's place. */}
      <span aria-hidden="true" className="hidden motion-reduce:inline-block shrink-0 h-2.5 w-2.5 bg-foreground" />
    </>
  );
}

/** The lines a row came from, or its summary when it has none. */
function Source({ row, size }: { row: Row; size: "row" | "pull" }) {
  const pull = size === "pull";
  return (
    <div className={pull ? "border-l-2 border-brand pl-4" : ""}>
      {row.takeOf !== null && (
        <p className="text-sm font-bold uppercase tracking-wide text-muted-foreground mb-1">{ANOTHER_TAKE}</p>
      )}
      {row.quote ? (
        <blockquote>
          <TranscriptLines
            lines={row.quote}
            className={pull ? "text-lg md:text-xl font-medium gap-1" : "text-base"}
          />
        </blockquote>
      ) : (
        <p className={`text-foreground ${pull ? "text-lg md:text-xl" : "text-base"}`}>{row.summary}</p>
      )}
    </div>
  );
}

function ProgressRows({ rows, stage, ratings, onFeedback, onSize }: BlockProps & { rows: Row[] }) {
  return (
    <ol className="mt-4 flex flex-col">
      {rows.map((row) => (
        <li
          key={row.key}
          aria-current={row.state === "active" ? "step" : undefined}
          className="grid gap-3 md:grid-cols-[minmax(0,18rem)_minmax(0,1fr)] md:gap-8 py-5 border-b border-border
                     last:border-b-0"
        >
          <Source row={row} size="row" />
          <div className="min-w-0">
            {row.state === "done" && row.meme && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                <MemeDisplay
                  url={row.meme.url}
                  alt={row.meme.situationText || row.summary}
                  className="flex justify-start"
                  maxHeightClassName="max-h-[45vh] md:max-h-80"
                  onSize={(w, h) => onSize(row.meme!.url, w, h)}
                />
                <div className="mt-1">
                  <MemeActions
                    url={row.meme.url}
                    memeId={row.meme.memeId}
                    rating={ratings[row.meme.url]}
                    onFeedback={(r) => onFeedback(row.meme!, r)}
                  />
                </div>
              </motion.div>
            )}
            {row.state === "active" && (
              <p className="flex items-center gap-2 text-base font-medium text-foreground">
                <Spinner />
                {stage ?? "Reading the message"}
              </p>
            )}
            {row.state === "waiting" && <p className="text-base text-muted-foreground">{UP_NEXT}</p>}
            {row.state === "failed" && <p className="text-base text-foreground">{FAILED_MOMENT}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Rows grouped for the results page: two tall memes in a row share it. */
function groupRows(rows: Row[], isTall: (row: Row) => boolean): Row[][] {
  const groups: Row[][] = [];
  for (let i = 0; i < rows.length; i++) {
    if (isTall(rows[i]) && i + 1 < rows.length && isTall(rows[i + 1])) {
      groups.push([rows[i], rows[i + 1]]);
      i++;
    } else {
      groups.push([rows[i]]);
    }
  }
  return groups;
}

function ResultRows(props: BlockProps & { rows: Row[] }) {
  const { rows, takes, sizes } = props;
  const memeOf = (row: Row) => takes[row.key]?.meme ?? row.meme;
  const isTall = (row: Row) => {
    const meme = memeOf(row);
    return !!meme && (sizes[meme.url] ?? 0) > TALL_RATIO;
  };
  const groups = groupRows(rows, isTall);

  return (
    <ol className="mt-6 flex flex-col gap-10 md:gap-14">
      {groups.map((group) =>
        group.length === 2 ? (
          // Two tall memes side by side, from 768px up, where each column
          // is still at least 320px wide.
          <li key={group[0].key} className="grid gap-10 md:grid-cols-2 md:gap-8">
            {group.map((row) => (
              <div key={row.key} className="flex flex-col gap-4 min-w-0">
                <Source row={row} size="pull" />
                <ResultMeme row={row} {...props} />
              </div>
            ))}
          </li>
        ) : (
          // One meme: lines above it on a phone, a pull quote beside it
          // from 1024px up, the meme taking the rest of the width.
          <li
            key={group[0].key}
            className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10 lg:items-start"
          >
            <Source row={group[0]} size="pull" />
            <ResultMeme row={group[0]} {...props} />
          </li>
        ),
      )}
    </ol>
  );
}

function ResultMeme({
  row,
  sub,
  takes,
  taking,
  takeStage,
  ratings,
  onFeedback,
  onSize,
  onAnotherTake,
}: BlockProps & { row: Row }) {
  const reduceMotion = useReducedMotion();
  const state = takes[row.key];
  const meme = state?.meme ?? row.meme;

  if (!meme) {
    return <p className="text-base text-foreground">{FAILED_MOMENT}</p>;
  }

  const busy = taking === row.key;
  const anotherTake = (
    <button
      type="button"
      onClick={() => onAnotherTake(sub, row)}
      disabled={taking !== null}
      aria-busy={busy}
      className={`${MEME_ACTION} disabled:opacity-40`}
    >
      <RefreshCw size={16} strokeWidth={2} aria-hidden="true" className={busy ? "motion-safe:animate-spin" : ""} />
      {ANOTHER_TAKE}
    </button>
  );

  return (
    <div className="min-w-0">
      {/* The new take fades in over the old one in the same frame, once
          its image has loaded. */}
      <div className="relative">
        <AnimatePresence initial={false} mode="popLayout">
          <motion.div
            key={meme.url}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={reduceMotion ? INSTANT : SETTLE}
          >
            <MemeDisplay
              url={meme.url}
              alt={meme.situationText || row.summary}
              className="flex justify-start"
              maxHeightClassName="max-h-[70vh] lg:max-h-[min(80vh,860px)]"
              onSize={(w, h) => onSize(meme.url, w, h)}
              heading={<Source row={row} size="row" />}
              footer={
                <MemeActions
                  url={meme.url}
                  memeId={meme.memeId}
                  rating={ratings[meme.url]}
                  onFeedback={(r) => onFeedback(meme, r)}
                />
              }
            />
          </motion.div>
        </AnimatePresence>
      </div>
      <div className="mt-1">
        <MemeActions
          key={meme.url}
          url={meme.url}
          memeId={meme.memeId}
          rating={ratings[meme.url]}
          onFeedback={(r) => onFeedback(meme, r)}
          lead={anotherTake}
        />
      </div>
      <p role="status" className="text-base text-foreground">
        {busy ? takeStage : state?.note ?? ""}
      </p>
    </div>
  );
}
