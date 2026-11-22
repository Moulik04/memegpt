"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, LayoutGroup, MotionConfig, motion, useReducedMotion } from "motion/react";
import { createConversation, getConversationMessages, postFeedback } from "@/lib/api";
import { useMemeStream, type StreamFailure, type ThinkingStage } from "@/hooks/useMemeStream";
import { useConversation } from "@/lib/ConversationContext";
import { useAuth } from "@/hooks/useAuth";
import {
  MAX_IMAGE_BYTES,
  MAX_IMAGES_PER_MESSAGE,
  PICK_TOO_LARGE,
  PICK_TOO_MANY,
  noticeFor,
  type Notice,
} from "@/lib/notices";
import { MemeDisplay } from "./MemeDisplay";
import { MemeActions } from "./MemeActions";
import BudgetNotice from "./BudgetNotice";
import type { MemeItem, PersistedMessage } from "@/types";

/** The copy deck's empty state and its four starter prompts. */
const EMPTY_LINE = "Something happened. We can work with that.";
const STARTER_PROMPTS = [
  "the meeting that could've been an email",
  "day 1 of the gym vs day 2",
  "starting the essay the night before it's due",
  "when the flight gets delayed for the third time",
];

/** One message and what came back for it. */
interface Turn {
  id: string;
  text: string;
  /** Preview URLs (blob:) of the photos sent with it, kept for the life of
   * the page so the sent message keeps showing them. */
  images?: string[];
  memes: MemeItem[];
  /** A text-only reply, such as when photos couldn't be looked at. */
  reply?: string;
  notice?: Notice & { budget: boolean };
  pending: boolean;
}

type Rating = "up" | "down";
type RateMeme = (meme: MemeItem, rating: Rating) => void;

interface PendingImage {
  file: File;
  previewUrl: string;
}

let turnCounter = 0;
const newTurnId = () => `turn-${Date.now()}-${turnCounter++}`;

/** A turn worth keeping under Earlier: it got a meme or a reply. */
const hasAnswer = (t: Turn) => t.memes.length > 0 || !!t.reply;

// Rebuilds turns from the one-row-per-meme table that
// GET /conversations/{id}/messages returns.
function turnsFromPersisted(rows: PersistedMessage[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;
  for (const row of rows) {
    if (row.role === "user") {
      current = { id: `saved-${row.id}`, text: row.content, memes: [], pending: false };
      turns.push(current);
      continue;
    }
    if (!current) {
      current = { id: `saved-${row.id}`, text: "", memes: [], pending: false };
      turns.push(current);
    }
    if (row.meme_url) {
      current.memes.push({ url: row.meme_url, situationText: row.content, memeId: row.meme_id ?? undefined });
    } else if (row.content) {
      current.reply = row.content;
    }
  }
  return turns;
}

function failureNotice(failure: StreamFailure, sentPhotos: boolean): Turn["notice"] {
  return {
    ...noticeFor(failure.message, { code: failure.code, hasReason: !!failure.reason, sentPhotos }),
    budget: failure.reason === "site_budget",
  };
}

const SETTLE = { duration: 0.32, ease: [0.16, 1, 0.3, 1] as const };

export function ChatWindow() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [pickError, setPickError] = useState<string | null>(null);
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  // By meme URL, so a rating survives the meme moving into Earlier or
  // opening full size.
  const [ratings, setRatings] = useState<Record<string, Rating>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingImagesRef = useRef<PendingImage[]>([]);
  const reduceMotion = useReducedMotion();

  const { user } = useAuth();
  const { conversationRowId, setConversationRowId, bumpRefresh } = useConversation();
  const { loading, stages, conversationId, submitText, submitImages } = useMemeStream("chat", conversationRowId);

  // Load a saved conversation when one is picked in History, and start
  // empty when the selection clears (New chat). Signed out, this never runs
  // past the first branch.
  useEffect(() => {
    if (!conversationRowId) {
      setTurns([]);
      return;
    }
    let cancelled = false;
    getConversationMessages(conversationRowId)
      .then((rows) => {
        if (!cancelled) setTurns(turnsFromPersisted(rows));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [conversationRowId]);

  useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  useEffect(() => {
    // Revoke only what was never sent, on unmount. Sent photos keep their
    // preview URLs for the life of the page.
    return () => {
      pendingImagesRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
  }, []);

  const handleFeedback = useCallback(
    async (meme: MemeItem, rating: Rating) => {
      setRatings((prev) => ({ ...prev, [meme.url]: rating }));
      // A rating only: which meme, which template, up or down. The text
      // behind the meme is not sent with it.
      await postFeedback({
        conversation_id: conversationId,
        template_id: meme.templateId || "",
        rating,
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
    setPickError(null);
  }

  // A pick that breaks a limit is turned away whole; photos already
  // attached stay.
  function handleFilesSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;
    if (files.some((f) => f.size > MAX_IMAGE_BYTES)) {
      setPickError(PICK_TOO_LARGE);
      return;
    }
    if (pendingImages.length + files.length > MAX_IMAGES_PER_MESSAGE) {
      setPickError(PICK_TOO_MANY);
      return;
    }
    setPendingImages((prev) => [...prev, ...files.map((file) => ({ file, previewUrl: URL.createObjectURL(file) }))]);
    setPickError(null);
  }

  async function submit(raw: string) {
    const text = raw.trim();
    const images = pendingImages;
    if ((!text && images.length === 0) || loading) return;

    const id = newTurnId();
    setTurns((prev) => [
      ...prev,
      { id, text, images: images.length > 0 ? images.map((p) => p.previewUrl) : undefined, memes: [], pending: true },
    ]);
    setInput("");
    // The preview URLs now belong to the sent turn: clear without revoking.
    setPendingImages([]);
    setPickError(null);
    scrollRef.current?.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });

    // Signed in with no conversation picked, the first message starts one,
    // so it's saved. The new id is passed straight through: state set here
    // isn't visible to this same call.
    let activeConversationRowId = conversationRowId;
    if (user && !activeConversationRowId) {
      const created = await createConversation("chat").catch(() => null);
      if (created) {
        activeConversationRowId = created.id;
        setConversationRowId(created.id);
      }
    }

    const { memes, plainReply, failure } =
      images.length > 0
        ? await submitImages(
            images.map((p) => p.file),
            text || undefined,
            undefined,
            undefined,
            activeConversationRowId,
          )
        : await submitText(text, undefined, undefined, activeConversationRowId);

    setTurns((prev) =>
      prev.map((t) =>
        t.id === id
          ? {
              ...t,
              memes,
              reply: memes.length === 0 ? (plainReply ?? undefined) : undefined,
              notice: memes.length === 0 && failure ? failureNotice(failure, images.length > 0) : undefined,
              pending: false,
            }
          : t,
      ),
    );

    if (activeConversationRowId) bumpRefresh();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(input);
  }

  function pickStarter(prompt: string) {
    setInput(prompt);
    inputRef.current?.focus();
  }

  const lead = turns.length > 0 ? turns[turns.length - 1] : null;
  const earlier = turns.slice(0, -1).filter(hasAnswer).reverse();
  const canSend = !loading && (input.trim().length > 0 || pendingImages.length > 0);

  return (
    <MotionConfig reducedMotion="user" transition={SETTLE}>
      <div className="flex flex-col flex-1 min-h-0">
        <h1 className="sr-only">Chat</h1>

        {/* The composer: on top from 768px up, where the next lead story
            appears; above the bottom tabs on a phone. */}
        <div className="order-last md:order-first shrink-0 border-t md:border-t-0 md:border-b border-border bg-background">
          <div className="mx-auto max-w-6xl px-4 md:px-8 py-3 md:py-5 lg:grid lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-12">
            <form onSubmit={handleSubmit} className="flex flex-col gap-2">
              {pendingImages.length > 0 && (
                <ul aria-label="Attached photos" className="flex flex-wrap gap-x-3 gap-y-1">
                  <AnimatePresence initial={false}>
                    {pendingImages.map((p, i) => (
                      <motion.li
                        key={p.previewUrl}
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
                        className="flex items-center gap-1"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element -- local preview */}
                        <img
                          src={p.previewUrl}
                          alt={`Attached photo ${i + 1}`}
                          className="w-12 h-12 object-cover border border-border"
                        />
                        <button
                          type="button"
                          onClick={() => removePendingImage(i)}
                          aria-label={`Remove photo ${i + 1}`}
                          className="min-h-11 px-2 text-base text-muted-foreground hover:text-foreground
                                     underline underline-offset-4 transition-colors duration-[var(--duration-fast)]"
                        >
                          Remove
                        </button>
                      </motion.li>
                    ))}
                  </AnimatePresence>
                </ul>
              )}

              <div className="flex flex-col md:flex-row gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  aria-label="Message"
                  enterKeyHint="send"
                  placeholder={pendingImages.length > 0 ? "Add a caption (optional)" : "What happened?"}
                  disabled={loading}
                  className="w-full md:flex-1 min-h-12 px-3 text-base bg-background border border-input rounded-sm
                             placeholder:text-muted-foreground disabled:opacity-60"
                />
                <div className="flex gap-2">
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
                    Send
                  </button>
                </div>
              </div>

              {pickError && (
                <p role="alert" className="text-base text-foreground border-l-2 border-brand pl-3">
                  {pickError}
                </p>
              )}
            </form>
          </div>
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto chat-scroll">
          <LayoutGroup>
            <div className="mx-auto max-w-6xl px-4 md:px-8 py-6 md:py-8 lg:grid lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-12">
              <section aria-label="Latest" className="min-w-0">
                {lead ? <LeadStory key={lead.id} turn={lead} stages={stages} ratings={ratings} onFeedback={handleFeedback} /> : (
                  <div className="max-w-2xl">
                    <h2 className="font-display text-4xl md:text-6xl leading-[0.95] text-foreground">{EMPTY_LINE}</h2>
                    <ul className="mt-6 md:mt-8 flex flex-col gap-1" aria-label="Starter prompts">
                      {STARTER_PROMPTS.map((p) => (
                        <li key={p}>
                          <button
                            type="button"
                            onClick={() => pickStarter(p)}
                            className="min-h-11 text-left text-lg text-foreground underline decoration-brand
                                       decoration-2 underline-offset-4 hover:decoration-[3px]"
                          >
                            {p}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>

              {earlier.length > 0 && (
                <aside aria-labelledby="earlier-heading" className="mt-10 lg:mt-0 min-w-0">
                  <h2
                    id="earlier-heading"
                    className="border-t-2 border-foreground pt-2 text-sm font-bold uppercase tracking-wide text-foreground"
                  >
                    Earlier
                  </h2>
                  <ol className="flex flex-col">
                    {earlier.map((turn) => (
                      <EarlierStory key={turn.id} turn={turn} ratings={ratings} onFeedback={handleFeedback} />
                    ))}
                  </ol>
                </aside>
              )}
            </div>
          </LayoutGroup>
        </div>
      </div>
    </MotionConfig>
  );
}

function UserLine({ turn, size }: { turn: Turn; size: "lead" | "earlier" }) {
  const lead = size === "lead";
  return (
    <motion.div layout="position" layoutId={`line-${turn.id}`} className="flex items-start gap-3">
      {turn.images && turn.images.length > 0 && (
        <div className="flex flex-wrap gap-1 shrink-0">
          {turn.images.map((src, i) => (
            // eslint-disable-next-line @next/next/no-img-element -- local preview
            <img
              key={src}
              src={src}
              alt={`Sent photo ${i + 1}`}
              className={`${lead ? "w-12 h-12" : "w-8 h-8"} object-cover border border-border`}
            />
          ))}
        </div>
      )}
      {turn.text && (
        <p
          className={
            lead
              ? "text-lg md:text-xl font-semibold leading-snug text-foreground"
              : "text-sm font-medium leading-snug text-foreground"
          }
        >
          {turn.text}
        </p>
      )}
    </motion.div>
  );
}

function Stages({ stages }: { stages: ThinkingStage[] }) {
  return (
    <ol aria-live="polite" className="mt-4 flex flex-col gap-1 text-base">
      {stages.map((stage, i) => {
        const current = i === stages.length - 1;
        return (
          <motion.li
            key={`${stage.key}-${stage.label}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className={current ? "text-foreground font-medium" : "text-muted-foreground"}
            aria-current={current ? "step" : undefined}
          >
            {stage.label}
          </motion.li>
        );
      })}
    </ol>
  );
}

function LeadStory({
  turn,
  stages,
  ratings,
  onFeedback,
}: {
  turn: Turn;
  stages: ThinkingStage[];
  ratings: Record<string, Rating>;
  onFeedback: RateMeme;
}) {
  const single = turn.memes.length === 1;
  const reduceMotion = useReducedMotion();
  return (
    // The old lead's line leaves from exactly where this one is drawn, so
    // this fades in once that line has moved off it.
    <motion.article
      initial={reduceMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: 0.12, ease: "easeOut" }}
    >
      <UserLine turn={turn} size="lead" />
      {turn.pending && <Stages stages={stages} />}

      {turn.notice &&
        (turn.notice.budget ? (
          <div className="mt-4">
            <BudgetNotice message={turn.notice.text} maxHeightClassName="max-h-[45vh]" />
          </div>
        ) : (
          <div role="alert" className="mt-4 text-base text-foreground border-l-2 border-brand pl-3 max-w-prose">
            {turn.notice.heading && <p className="font-semibold">{turn.notice.heading}</p>}
            <p>{turn.notice.text}</p>
          </div>
        ))}

      {turn.reply && <p className="mt-4 text-lg text-foreground max-w-prose">{turn.reply}</p>}

      <div className="flex flex-col gap-8">
        {turn.memes.map((meme, i) => (
          // From 1024px up, one meme sits in a slot of fixed minimum height,
          // so the page doesn't jump between tall and wide answers. The
          // image is centered in it, with its action row lined up under the
          // image. On narrower screens the row keeps the column's full width
          // so it never wraps under a tall meme.
          <div
            key={meme.url}
            className={`mt-4 flex flex-col items-center justify-center ${single ? "lg:min-h-[min(66vh,700px)]" : ""}`}
          >
            <div className="w-full lg:w-fit max-w-full">
              <motion.div layoutId={`meme-${turn.id}-${i}`}>
                <MemeDisplay
                  url={meme.url}
                  alt={meme.situationText || turn.text || "A meme from MemeGPT"}
                  className="flex justify-center max-w-full"
                  maxHeightClassName="max-h-[55vh] lg:max-h-[min(62vh,640px)]"
                />
              </motion.div>
              <div className="mt-2">
                <MemeActions
                  url={meme.url}
                  memeId={meme.memeId}
                  rating={ratings[meme.url]}
                  onFeedback={(r) => onFeedback(meme, r)}
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </motion.article>
  );
}

function EarlierStory({
  turn,
  ratings,
  onFeedback,
}: {
  turn: Turn;
  ratings: Record<string, Rating>;
  onFeedback: RateMeme;
}) {
  return (
    <li className="py-5 border-b border-border last:border-b-0">
      <UserLine turn={turn} size="earlier" />
      {turn.reply && <p className="mt-2 text-sm text-muted-foreground">{turn.reply}</p>}
      {turn.memes.map((meme, i) => (
        <motion.div key={meme.url} layoutId={`meme-${turn.id}-${i}`} className="mt-2 w-3/4 md:w-full">
          <MemeDisplay
            url={meme.url}
            alt={meme.situationText || turn.text || "A meme from MemeGPT"}
            className="flex justify-start"
            maxHeightClassName="max-h-48 lg:max-h-56"
            heading={turn.text ? <p className="text-base font-semibold text-foreground pr-2">{turn.text}</p> : undefined}
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
      ))}
    </li>
  );
}
