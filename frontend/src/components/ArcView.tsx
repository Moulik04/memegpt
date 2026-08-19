"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { motion } from "motion/react";
import { createArcCard, getArc, memeImageUrl } from "@/lib/api";
import { MemeCard } from "./MemeCard";
import { Gauge } from "./charts/gauge";
import type { ArcStats } from "@/types";

// Arc — Story-style tap-through reveal (same pattern Spotify Wrapped
// popularized for exactly this use case). Stripped down to plain,
// token-based styling for now (no glow/gradient) — a dedicated visual
// pass for Arc's reveal is a separate, later effort, not part of this
// phase's monochrome-foundation work.

const STEP_DURATION_MS = 3800;

// Mirrors backend/arc/copy.py's _TIER_THRESHOLDS — the aura value just
// below "aura farming god" (the uncapped top tier). Used only to give the
// finale gauge a meaningful 100% mark ("how close to god-tier"), not a
// real cap on the aura score itself.
const AURA_GOD_TIER_THRESHOLD = 20_000;

type Step =
  // `numeric` is set only for genuinely numeric stats (total memes, streak
  // days) — it drives OdometerNumber's digit-roll. Steps whose `big` is
  // free-form text (a time label, a template name, "3 / 5") leave it unset
  // and just render `big` as plain text, same as before.
  | { kind: "stat"; kicker: string; big: string; numeric?: number; small?: boolean; cap: React.ReactNode }
  | { kind: "image"; kicker: string; imageUrl: string; name: string; cap: React.ReactNode }
  | { kind: "finale" };

// Odometer-style digit roll — each digit is its own sliding column (10
// stacked 0-9 rows, translated by -{digit}em), non-digit characters
// (commas, slashes) render as static text. em-based offset instead of a
// measured pixel height, so it scales correctly across the different
// font sizes stat slides use without a ResizeObserver.
function OdometerDigit({ char }: { char: string }) {
  if (!/[0-9]/.test(char)) {
    return <span>{char}</span>;
  }
  const n = Number(char);
  return (
    <span className="inline-block h-[1em] overflow-hidden align-top">
      <motion.span
        className="flex flex-col"
        initial={{ y: 0 }}
        animate={{ y: `-${n}em` }}
        transition={{ type: "spring", stiffness: 180, damping: 22 }}
      >
        {Array.from({ length: 10 }, (_, i) => (
          <span key={i} className="h-[1em] leading-none">
            {i}
          </span>
        ))}
      </motion.span>
    </span>
  );
}

function OdometerNumber({ value }: { value: number }) {
  return (
    <span className="inline-flex tabular-nums">
      {value
        .toLocaleString()
        .split("")
        .map((char, i) => (
          <OdometerDigit key={i} char={char} />
        ))}
    </span>
  );
}

function formatShortDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatSpan(startIso: string, endIso: string): string {
  const start = new Date(`${startIso}T00:00:00`);
  const end = new Date(`${endIso}T00:00:00`);
  if (start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth()) {
    return start.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  }
  const startStr = start.toLocaleDateString("en-US", { month: "short" });
  const endStr = end.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  return `${startStr}–${endStr}`;
}

function buildSteps(stats: ArcStats): Step[] {
  const steps: Step[] = [
    {
      kind: "stat",
      kicker: "01 / VOLUME",
      big: String(stats.total_memes),
      numeric: stats.total_memes,
      cap: <>memes generated this arc. <span className="text-accent">no thoughts, just memes.</span></>,
    },
  ];

  const top = stats.top_templates[0];
  if (top) {
    const cap = <>your most-summoned template. <span className="text-accent">{top.roast}</span></>;
    steps.push(
      top.image_url
        ? { kind: "image", kicker: "02 / SIGNATURE", imageUrl: top.image_url, name: top.display_name, cap }
        : { kind: "stat", kicker: "02 / SIGNATURE", big: top.display_name, small: true, cap },
    );
  }

  if (stats.busiest_time_label) {
    steps.push({
      kind: "stat",
      kicker: "03 / WITCHING HOUR",
      big: stats.busiest_time_label,
      small: true,
      cap: (
        <>
          busiest moment{stats.busiest_date ? `, ${formatShortDate(stats.busiest_date)}` : ""}.{" "}
          {stats.hour_roast && <span className="text-accent">{stats.hour_roast}</span>}
        </>
      ),
    });
  }

  steps.push({
    kind: "stat",
    kicker: "04 / THE SPLIT",
    big: `${stats.chat_count} / ${stats.lore_count} / ${stats.make_count}`,
    small: true,
    cap: <>chat / lore / make. {stats.split_roast && <span className="text-accent">{stats.split_roast}</span>}</>,
  });

  steps.push({
    kind: "stat",
    kicker: "05 / STREAK",
    big: String(stats.longest_streak_days),
    numeric: stats.longest_streak_days,
    cap: (
      <>
        consecutive days.{" "}
        <span className="text-accent">{stats.longest_streak_days >= 7 ? "no days off." : "still an arc."}</span>
      </>
    ),
  });

  steps.push({ kind: "finale" });
  return steps;
}

function ArcStatSlide({ step }: { step: Extract<Step, { kind: "stat" }> }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-8">
      <span className="font-mono text-[10px] tracking-widest uppercase text-gray-500 mb-3">{step.kicker}</span>
      <span
        className={`font-black tracking-tight leading-none text-paper ${
          step.small ? "text-4xl" : "text-6xl"
        }`}
      >
        {step.numeric !== undefined ? <OdometerNumber value={step.numeric} /> : step.big}
      </span>
      <p className="mt-4 font-mono text-sm text-gray-400 leading-relaxed max-w-[26ch]">{step.cap}</p>
    </div>
  );
}

function ArcImageSlide({ step }: { step: Extract<Step, { kind: "image" }> }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-8">
      <span className="font-mono text-[10px] tracking-widest uppercase text-gray-500 mb-3">{step.kicker}</span>
      <Image
        src={memeImageUrl(step.imageUrl)}
        alt={step.name}
        width={150}
        height={150}
        unoptimized
        className="w-[150px] h-[150px] object-cover rounded-2xl border-2 border-border"
      />
      <p className="mt-3 font-extrabold text-lg tracking-tight">{step.name}</p>
      <p className="mt-2 font-mono text-sm text-gray-400 leading-relaxed max-w-[26ch]">{step.cap}</p>
    </div>
  );
}

function ArcFinaleSlide({ stats }: { stats: ArcStats }) {
  const top = stats.top_templates[0];
  return (
    <div className="absolute inset-0 px-7 pt-14 pb-7 flex flex-col items-center text-center">
      <div className="absolute top-6 left-6 font-black text-xs tracking-wide">MEMEGPT ARC.</div>
      {stats.tier && (
        <div className="absolute top-5 right-6 font-mono text-[9px] bg-ink-2 border border-border rounded-full px-2.5 py-1 whitespace-nowrap">
          {stats.tier.toUpperCase()}
        </div>
      )}
      {stats.period_label && (
        <div className="absolute top-12 left-6 right-6 text-[9.5px] tracking-widest uppercase text-gray-400 text-left">
          {stats.period_label.toUpperCase()}
          {stats.date_span_start && stats.date_span_end && ` · ${formatSpan(stats.date_span_start, stats.date_span_end).toUpperCase()}`}
        </div>
      )}

      <div className="mt-6 w-full max-w-[230px]">
        <Gauge
          value={Math.min(100, (stats.aura / AURA_GOD_TIER_THRESHOLD) * 100)}
          centerValue={stats.aura}
          prefix="+"
          defaultLabel="AURA FARMED"
          totalNotches={36}
          activeFill="var(--accent-color)"
          inactiveFill="var(--line)"
          inactiveFillOpacity={0.6}
          width={230}
          height={165}
        />
      </div>

      <div className="mt-auto w-full font-mono text-[9.5px] text-gray-400 leading-relaxed border-t border-border pt-2.5 text-left space-y-0.5">
        <div>&rsaquo; {stats.total_memes} memes generated</div>
        {top && (
          <div>
            &rsaquo; top: {top.display_name} <span className="text-accent">{top.roast}</span>
          </div>
        )}
        {stats.busiest_time_label && (
          <div>
            &rsaquo; busiest: {stats.busiest_time_label}{" "}
            {stats.hour_roast && <span className="text-accent">{stats.hour_roast}</span>}
          </div>
        )}
        <div>&rsaquo; streak: {stats.longest_streak_days} days</div>
      </div>

      {stats.verdict && (
        <p className="mt-3 text-[10px] font-extrabold uppercase text-white leading-snug">{stats.verdict}</p>
      )}
    </div>
  );
}

function ArcEmptyState({ totalMemes }: { totalMemes: number }) {
  const pct = Math.min(100, Math.round((totalMemes / 5) * 100));
  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <div className="arrive-settle relative max-w-sm w-full rounded-[26px] border border-border bg-card px-8 py-14 text-center overflow-hidden">
        <div className="relative text-4xl mb-4">🔮</div>
        <h2 className="relative text-xl font-black tracking-tight mb-2">Your arc hasn&apos;t started yet.</h2>
        <p className="relative text-sm text-gray-400 leading-relaxed mb-6 max-w-[40ch] mx-auto">
          Go be unwell somewhere. Five memes minimum before MemeGPT has anything to judge you for.
        </p>
        <div className="relative max-w-[220px] mx-auto mb-6">
          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
            <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-2 font-mono text-[11px] text-gray-600">{totalMemes} / 5 memes toward your first Arc</p>
        </div>
        <Link
          href="/chat"
          className="relative inline-block bg-accent hover:bg-accent/90 transition-colors text-white
                     font-semibold text-sm px-6 py-3 rounded-full"
        >
          Go make some memes
        </Link>
      </div>
    </div>
  );
}

function ArcShareScreen({ url }: { url: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-10 gap-6">
      <div className="arrive-settle max-w-sm w-full">
        <MemeCard url={url} alt="My MemeGPT Arc" large />
      </div>
      <Link href="/chat" className="text-xs text-gray-500 hover:text-gray-300 transition-colors">
        Make another meme
      </Link>
    </div>
  );
}

export function ArcView() {
  const [stats, setStats] = useState<ArcStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const [cardResult, setCardResult] = useState<{ meme_id: string; url: string } | null>(null);
  const [creatingCard, setCreatingCard] = useState(false);
  const [cardError, setCardError] = useState<string | null>(null);

  // Resolved once per mount — Intl is a browser API, safe here since this
  // whole component is "use client" and never runs during SSR.
  const [tz] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");

  useEffect(() => {
    let cancelled = false;
    getArc(tz)
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load your Arc.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tz]);

  const steps = useMemo(() => (stats && stats.has_enough ? buildSteps(stats) : []), [stats]);
  const isFinale = steps.length > 0 && stepIndex === steps.length - 1;

  // Auto-advance, story-style — stops at the finale (that's the resting
  // point where the user decides to share, not just another beat to
  // scroll past) and pauses entirely once the share screen is showing.
  useEffect(() => {
    if (steps.length === 0 || isFinale || cardResult) return;
    setProgress(0);
    const start = Date.now();
    const id = setInterval(() => {
      const p = Math.min(1, (Date.now() - start) / STEP_DURATION_MS);
      setProgress(p);
      if (p >= 1) {
        clearInterval(id);
        setStepIndex((i) => Math.min(steps.length - 1, i + 1));
      }
    }, 60);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepIndex, steps.length, cardResult]);

  async function handleShare() {
    setCreatingCard(true);
    setCardError(null);
    try {
      const result = await createArcCard(tz);
      setCardResult(result);
    } catch (err) {
      setCardError(err instanceof Error ? err.message : "Couldn't create your Arc card — try again.");
    } finally {
      setCreatingCard(false);
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-gray-500">Calculating your arc…</p>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div className="flex-1 flex items-center justify-center px-6">
        <p className="text-sm text-red-400">{error ?? "Couldn't load your Arc — try again."}</p>
      </div>
    );
  }

  if (!stats.has_enough) {
    return <ArcEmptyState totalMemes={stats.total_memes} />;
  }

  if (cardResult) {
    return <ArcShareScreen url={cardResult.url} />;
  }

  const step = steps[stepIndex];

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 chat-scroll flex flex-col items-center">
      <div className="arrive-settle relative w-full max-w-[380px] aspect-[3.6/5] rounded-[28px] overflow-hidden border border-border bg-card shadow-2xl shadow-black/60 select-none">
        <div className="absolute top-3 left-3 right-3 z-20 flex gap-1">
          {steps.map((_, i) => (
            <div key={i} className="flex-1 h-[3px] rounded-full bg-white/15 overflow-hidden">
              <div
                className="h-full bg-white rounded-full"
                style={{ width: i < stepIndex ? "100%" : i === stepIndex ? `${progress * 100}%` : "0%" }}
              />
            </div>
          ))}
        </div>

        <div className="absolute top-6 left-4 right-4 z-20 flex items-center justify-between">
          <span className="text-[10px] font-mono text-gray-500 tracking-wide">YOUR ARC</span>
          <Link href="/chat" className="text-gray-500 text-base leading-none" title="Exit" aria-label="Exit to Chat">
            ✕
          </Link>
        </div>

        <button
          aria-label="Previous"
          onClick={() => setStepIndex((i) => Math.max(0, i - 1))}
          className="absolute inset-y-0 left-0 w-1/3 z-10"
        />
        <button
          aria-label="Next"
          onClick={() => setStepIndex((i) => Math.min(steps.length - 1, i + 1))}
          className="absolute inset-y-0 right-0 w-1/3 z-10"
        />

        {step.kind === "finale" ? (
          <ArcFinaleSlide stats={stats} />
        ) : step.kind === "image" ? (
          <ArcImageSlide step={step} />
        ) : (
          <ArcStatSlide step={step} />
        )}
      </div>

      {isFinale ? (
        <div className="mt-6 w-full max-w-[380px] flex flex-col items-center gap-2">
          {cardError && <p className="text-xs text-red-400">{cardError}</p>}
          <button
            onClick={handleShare}
            disabled={creatingCard}
            className="w-full py-3 rounded-xl bg-accent hover:bg-accent/90 disabled:opacity-50
                       text-white font-semibold text-sm transition-colors"
          >
            {creatingCard ? "Rendering your Arc…" : "Share your Arc"}
          </button>
        </div>
      ) : (
        <p className="mt-4 text-[11px] text-gray-600">tap right to advance &middot; tap left to go back</p>
      )}
    </div>
  );
}
