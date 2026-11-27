"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { INSTANT, SETTLE } from "@/lib/motion";
import { ArrowLeft, ArrowRight, X } from "lucide-react";
import { ApiError, createArcCard, getArc, memeImageUrl } from "@/lib/api";
import { arcSeasonLine, daysLabel, ladderPosition, timesLabel } from "@/lib/arcFormat";
import { GENERAL_FAILURE, type Notice } from "@/lib/notices";
import { MemeDisplay } from "./MemeDisplay";
import { MEME_ACTION, MemeActions } from "./MemeActions";
import { MotionSafeImg } from "./StillImage";
import { templateDisplayName } from "@/lib/templateNames";
import type { ArcCardResponse, ArcStats } from "@/types";

// Arc: a tap-through story staged like a sports back page. Five frames,
// then the finale and its share card. Nothing advances on a timer.

const MIN_MEMES = 5;

/** Copy deck, section 7.7. */
const LOADING = "Calculating your Arc…";
const EMPTY_HEADING = "Your arc hasn't started yet.";
const EMPTY_TEXT = "Go be unwell somewhere. Five memes minimum before MemeGPT has anything to judge you for.";
const START_IN_CHAT = "Start in Chat";
const SHARE = "Share your Arc";
const RENDERING = "Rendering…";
const BACK_TO_ARC = "Back to your Arc";

/** The small uppercase line used for labels across the redesign. */
const LABEL = "text-sm font-bold uppercase tracking-wide";
// Without its display, so a caller can hide it at some widths.
const LINK_LOOK =
  "items-center gap-1.5 min-h-11 text-base font-medium text-foreground underline decoration-brand " +
  "decoration-2 underline-offset-4 hover:decoration-[3px]";
const TEXT_LINK = `inline-flex ${LINK_LOOK}`;

interface Frame {
  label: string;
  body: React.ReactNode;
}

/** A roast after its fixed lead-in, the punchline in red. */
function Roast({ lead, line }: { lead?: string; line?: string | null }) {
  if (!lead && !line) return null;
  return (
    <p className="text-lg md:text-xl leading-snug text-foreground max-w-[32ch]">
      {lead}
      {lead && line ? " " : ""}
      {line && <span className="font-semibold text-brand">{line}</span>}
    </p>
  );
}

/** A display number or word, Anton, as big as the frame allows. */
function Display({ children, size = "lg" }: { children: React.ReactNode; size?: "lg" | "md" }) {
  return (
    <p
      className={`font-display leading-[0.9] text-foreground break-words ${
        size === "lg" ? "text-[6rem] md:text-[10rem]" : "text-5xl md:text-7xl"
      }`}
    >
      {children}
    </p>
  );
}

function buildFrames(stats: ArcStats): Frame[] {
  const frames: Frame[] = [
    {
      label: "01 Volume",
      body: (
        <>
          <p className="font-display text-2xl md:text-4xl leading-tight text-foreground">
            {arcSeasonLine(stats.period_label, stats.date_span_start, stats.date_span_end)}
          </p>
          <Display>{stats.total_memes.toLocaleString("en-US")}</Display>
          <Roast lead="memes generated this arc." line={stats.volume_roast} />
        </>
      ),
    },
  ];

  const top = stats.top_templates[0];
  if (top) {
    const topName = templateDisplayName(top.template_id, top.display_name);
    frames.push({
      label: "02 Signature",
      body: (
        <>
          {top.image_url && (
            <figure className="w-fit max-w-full bg-meme-mat border border-meme-edge p-2 md:p-3">
              <MotionSafeImg
                src={memeImageUrl(top.image_url)}
                alt={topName}
                className="block w-auto h-auto max-w-full max-h-[36vh] md:max-h-[32vh] border border-meme-edge"
              />
            </figure>
          )}
          <div>
            <p className="font-display text-4xl md:text-5xl leading-none text-foreground break-words">
              {topName}
            </p>
            <p className="mt-2 text-xl font-bold text-foreground">{timesLabel(top.count)}</p>
          </div>
          <Roast lead="your most-summoned template." line={top.roast} />
        </>
      ),
    });
  }

  // The busiest hour and the roast written for it. A backend without the
  // hour's own roast sends both fields about one moment, so hour_roast fits.
  const hour = stats.busiest_hour_label ?? stats.busiest_time_label;
  const hourRoast = stats.busiest_hour_label ? (stats.busiest_hour_roast ?? stats.hour_roast) : stats.hour_roast;
  if (hour) {
    frames.push({
      label: "03 Witching hour",
      body: (
        <>
          <Display>{hour}</Display>
          <Roast line={hourRoast} />
        </>
      ),
    });
  }

  frames.push({
    label: "04 The split",
    body: (
      <>
        {/* Equal widths, so every label stays readable whatever the counts. */}
        <dl className="grid grid-cols-3 gap-2 md:gap-3 w-full max-w-2xl">
          {(
            [
              ["Chat", stats.chat_count],
              ["Lore", stats.lore_count],
              ["Make", stats.make_count],
            ] as const
          ).map(([name, count]) => (
            <div key={name} className="flex flex-col-reverse justify-between gap-6 bg-brand px-3 py-4 md:px-5 md:py-6">
              <dt className={`${LABEL} text-primary-foreground`}>{name}</dt>
              <dd className="font-display text-5xl md:text-7xl leading-none text-primary-foreground">
                {count.toLocaleString("en-US")}
              </dd>
            </div>
          ))}
        </dl>
        <Roast lead="chat / lore / make." line={stats.split_roast} />
      </>
    ),
  });

  frames.push({
    label: "05 Streak",
    body: (
      <>
        <Display>{daysLabel(stats.longest_streak_days)}</Display>
        <Roast lead="consecutive days." line={stats.streak_roast} />
      </>
    ),
  });

  return frames;
}

function Finale({
  stats,
  onShare,
  rendering,
  notice,
}: {
  stats: ArcStats;
  onShare: () => void;
  rendering: boolean;
  notice: Notice | null;
}) {
  const tiers = stats.tiers ?? [];
  const { index, next } = ladderPosition(tiers, stats.tier, stats.aura);
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:gap-12 lg:items-start">
      <div className="flex flex-col gap-4 min-w-0">
        <div className="w-fit max-w-full bg-brand px-5 py-4 md:px-7 md:py-5 text-primary-foreground">
          <p className="font-display text-6xl md:text-8xl leading-none break-words">
            +{stats.aura.toLocaleString("en-US")}
          </p>
          <p className="mt-2 font-display text-2xl md:text-3xl leading-none">AURA FARMED</p>
        </div>
        {stats.tier && (
          <p className="w-fit max-w-full bg-foreground px-4 py-2 text-xl md:text-2xl font-bold text-background">
            {stats.tier}
          </p>
        )}
        {stats.verdict && (
          <p className="mt-2 text-3xl md:text-5xl font-extrabold leading-tight text-foreground max-w-[20ch]">
            {stats.verdict}
          </p>
        )}
        <div className="mt-2 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-4">
            <button
              type="button"
              onClick={onShare}
              disabled={rendering}
              aria-busy={rendering}
              className="w-full sm:w-auto min-h-12 px-8 rounded-sm bg-primary text-primary-foreground text-base
                         font-semibold hover:bg-primary/85 disabled:opacity-40
                         transition-colors duration-[var(--duration-fast)]"
            >
              {SHARE}
            </button>
            <p role="status" className="text-base text-foreground">
              {rendering ? RENDERING : ""}
            </p>
          </div>
          {notice && <NoticeBlock notice={notice} />}
        </div>
      </div>

      {tiers.length > 0 && (
        <section aria-labelledby="arc-tiers" className="min-w-0">
          <h3 id="arc-tiers" className={`${LABEL} border-t-2 border-foreground pt-2 text-foreground`}>
            Tiers
          </h3>
          <ol className="mt-2">
            {tiers.map((t, i) => {
              const current = i === index;
              return (
                <li
                  key={t.name}
                  aria-current={current ? "true" : undefined}
                  className={`flex items-baseline justify-between gap-4 border-b border-border py-2.5 text-base ${
                    current ? "border-l-4 border-l-brand pl-3 font-bold text-foreground" : "text-muted-foreground"
                  }`}
                >
                  <span className="min-w-0">{t.name}</span>
                  <span className="shrink-0 tabular-nums">{t.min_aura.toLocaleString("en-US")}</span>
                </li>
              );
            })}
          </ol>
          {next && (
            <p className="mt-3 text-base font-semibold text-brand">
              {next.distance.toLocaleString("en-US")} to {next.name}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

function NoticeBlock({ notice, onRetry }: { notice: Notice; onRetry?: () => void }) {
  return (
    <div role="alert" className="border-l-2 border-brand pl-3 max-w-prose">
      {notice.heading && <p className="text-base font-semibold text-foreground">{notice.heading}</p>}
      <p className="text-base text-foreground">{notice.text}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className={TEXT_LINK}>
          Try again
        </button>
      )}
    </div>
  );
}

/** A failed card render: a notice the backend named (busy) keeps its
 * wording, anything else is the deck's general failure. */
function cardNotice(err: unknown): Notice {
  if (err instanceof ApiError && err.reason) return { text: err.message };
  return GENERAL_FAILURE;
}

function EmptyState({ totalMemes }: { totalMemes: number }) {
  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <h2 className="font-display text-4xl md:text-6xl leading-none text-foreground">{EMPTY_HEADING}</h2>
      <p className="text-lg text-foreground max-w-prose">{EMPTY_TEXT}</p>
      <p className="text-sm text-muted-foreground">
        {Math.min(totalMemes, MIN_MEMES)} of {MIN_MEMES} memes so far.
      </p>
      <Link href="/chat" className={`${TEXT_LINK} self-start`}>
        {START_IN_CHAT}
        <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
      </Link>
    </div>
  );
}

export function ArcView() {
  const [stats, setStats] = useState<ArcStats | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // 0..frames.length-1 are the frames; frames.length is the finale.
  const [position, setPosition] = useState(0);
  const [direction, setDirection] = useState<1 | -1>(1);
  const [card, setCard] = useState<ArcCardResponse | null>(null);
  const [rendering, setRendering] = useState(false);
  const [cardNoticeState, setCardNotice] = useState<Notice | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reduceMotion = useReducedMotion();

  // Resolved once per mount; this component never renders on the server.
  const [tz] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");

  useEffect(() => {
    let cancelled = false;
    setLoadFailed(false);
    getArc(tz)
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [tz, attempt]);

  const frames = useMemo(() => (stats?.has_enough ? buildFrames(stats) : []), [stats]);
  const atFinale = frames.length > 0 && position === frames.length;

  const go = useCallback(
    (step: 1 | -1) => {
      setDirection(step);
      setPosition((p) => Math.min(frames.length, Math.max(0, p + step)));
    },
    [frames.length],
  );

  // Arrow keys step through the story, except while typing or on the card.
  useEffect(() => {
    if (frames.length === 0 || card) return;
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable=true]")) return;
      if (e.key === "ArrowRight") go(1);
      if (e.key === "ArrowLeft") go(-1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [frames.length, card, go]);

  // The card and coming back from it move focus to what's now on screen.
  const cardShown = card !== null;
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [cardShown]);

  async function share() {
    if (rendering) return;
    setRendering(true);
    setCardNotice(null);
    try {
      setCard(await createArcCard(tz));
    } catch (err) {
      setCardNotice(cardNotice(err));
    } finally {
      setRendering(false);
    }
  }

  let content: React.ReactNode;
  if (loadFailed) {
    content = <NoticeBlock notice={GENERAL_FAILURE} onRetry={() => setAttempt((n) => n + 1)} />;
  } else if (!stats) {
    content = (
      <p role="status" className="text-base text-muted-foreground">
        {LOADING}
      </p>
    );
  } else if (!stats.has_enough) {
    content = <EmptyState totalMemes={stats.total_memes} />;
  } else if (card) {
    content = (
      <div className="flex flex-col gap-4">
        <h2 ref={headingRef} tabIndex={-1} className="sr-only">
          {SHARE}
        </h2>
        <div className="w-full lg:w-fit max-w-full">
          <MemeDisplay
            url={card.url}
            alt="Your MemeGPT Arc"
            className="flex justify-start"
            maxHeightClassName="max-h-[60vh] lg:max-h-[min(72vh,760px)]"
          />
          <div className="mt-1">
            <MemeActions
              url={card.url}
              memeId={card.meme_id}
              leadInline
              lead={
                <button type="button" onClick={() => setCard(null)} className={MEME_ACTION}>
                  <ArrowLeft size={16} strokeWidth={2} aria-hidden="true" />
                  {BACK_TO_ARC}
                </button>
              }
            />
          </div>
        </div>
      </div>
    );
  } else {
    const label = atFinale ? null : frames[position].label;
    content = (
      <section aria-roledescription="story" aria-label="Your Arc" className="flex flex-col gap-6">
        <div className="flex items-center gap-4">
          {/* Progress, not a timer: a segment fills once its frame is reached. */}
          <ol className="flex-1 grid gap-1.5" style={{ gridTemplateColumns: `repeat(${frames.length}, minmax(0, 1fr))` }}>
            {frames.map((f, i) => (
              <li key={f.label} className={`h-1.5 ${i <= position ? "bg-brand" : "bg-border"}`}>
                <span className="sr-only">
                  {f.label}
                  {i === position ? ", current" : i < position ? ", seen" : ""}
                </span>
              </li>
            ))}
          </ol>
          <Link href="/chat" className={`hidden md:inline-flex ${LINK_LOOK} no-underline hover:underline`}>
            <X size={18} strokeWidth={2} aria-hidden="true" />
            Close
          </Link>
        </div>

        <div
          // Tapping either half of the frame steps back or on, story-style.
          // The Back and Next buttons below do the same for every input.
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            go(e.clientX - r.left < r.width / 2 ? -1 : 1);
          }}
          className="relative min-h-[60vh] md:min-h-[56vh] overflow-hidden select-none cursor-pointer"
        >
          <AnimatePresence mode="popLayout" initial={false} custom={direction}>
            <motion.div
              key={position}
              custom={direction}
              initial={reduceMotion ? false : { opacity: 0, x: 32 * direction }}
              animate={{ opacity: 1, x: 0 }}
              exit={reduceMotion ? { opacity: 0, transition: INSTANT } : { opacity: 0, x: -32 * direction }}
              transition={SETTLE}
              className="flex flex-col items-start gap-5 md:gap-6"
            >
              {label ? (
                <>
                  <h2 className={`${LABEL} text-foreground`}>{label}</h2>
                  {frames[position].body}
                </>
              ) : (
                <>
                  <h2 className="sr-only">{stats.period_label ?? "Your Arc"}</h2>
                  <div className="w-full cursor-auto" onClick={(e) => e.stopPropagation()}>
                    <Finale stats={stats} onShare={share} rendering={rendering} notice={cardNoticeState} />
                  </div>
                </>
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-border pt-2">
          <button
            type="button"
            onClick={() => go(-1)}
            disabled={position === 0}
            className={`${TEXT_LINK} no-underline disabled:opacity-40 disabled:cursor-not-allowed px-1`}
          >
            <ArrowLeft size={16} strokeWidth={2} aria-hidden="true" />
            Back
          </button>
          <p aria-live="polite" className="sr-only">
            {label ?? ""}
          </p>
          <button
            type="button"
            onClick={() => go(1)}
            disabled={atFinale}
            className={`${TEXT_LINK} no-underline disabled:opacity-40 disabled:cursor-not-allowed px-1`}
          >
            Next
            <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
      </section>
    );
  }

  return (
    <main className="flex-1 overflow-y-auto chat-scroll">
      <div className="mx-auto max-w-5xl px-4 md:px-8 pt-6 md:pt-8 pb-12">
        <h1 className="sr-only">Arc</h1>
        {content}
      </div>
    </main>
  );
}

