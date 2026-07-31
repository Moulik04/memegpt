"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { createArcCard, getArc, memeImageUrl } from "@/lib/api";
import { ShareButtons } from "./ShareButtons";
import type { ArcStats } from "@/types";

// Growth Phase D — Arc. Story-style tap-through reveal (same pattern
// Spotify Wrapped popularized for exactly this use case), ported from the
// Artifact concept approved by the project owner across two review rounds
// (share-card visual + roast voice, then the reveal pacing/navigation).
// Colors are the approved aura palette, not this app's `brand` Tailwind
// scale — kept as literal hex so the porting is exact, matching how the
// rest of the app already reaches for arbitrary values (e.g. bg-[#13131e]).

const STEP_DURATION_MS = 3800;

type Step =
  | { kind: "stat"; kicker: string; big: string; small?: boolean; cap: React.ReactNode; glow: string }
  | { kind: "image"; kicker: string; imageUrl: string; name: string; cap: React.ReactNode; glow: string }
  | { kind: "finale" };

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
      cap: <>memes generated this arc. <span className="text-[#ff5db1]">no thoughts, just memes.</span></>,
      glow: "rgba(168,85,247,0.35)",
    },
  ];

  const top = stats.top_templates[0];
  if (top) {
    const cap = <>your most-summoned template. <span className="text-[#ff5db1]">{top.roast}</span></>;
    steps.push(
      top.image_url
        ? { kind: "image", kicker: "02 / SIGNATURE", imageUrl: top.image_url, name: top.display_name, cap, glow: "rgba(232,121,249,0.32)" }
        : { kind: "stat", kicker: "02 / SIGNATURE", big: top.display_name, small: true, cap, glow: "rgba(232,121,249,0.32)" },
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
          {stats.hour_roast && <span className="text-[#ff5db1]">{stats.hour_roast}</span>}
        </>
      ),
      glow: "rgba(255,93,177,0.3)",
    });
  }

  steps.push({
    kind: "stat",
    kicker: "04 / THE SPLIT",
    big: `${stats.chat_count} / ${stats.lore_count}`,
    small: true,
    cap: <>chat / lore memes. {stats.split_roast && <span className="text-[#ff5db1]">{stats.split_roast}</span>}</>,
    glow: "rgba(34,211,238,0.28)",
  });

  steps.push({
    kind: "stat",
    kicker: "05 / STREAK",
    big: String(stats.longest_streak_days),
    cap: (
      <>
        consecutive days.{" "}
        <span className="text-[#ff5db1]">{stats.longest_streak_days >= 7 ? "no days off." : "still an arc."}</span>
      </>
    ),
    glow: "rgba(168,85,247,0.32)",
  });

  steps.push({ kind: "finale" });
  return steps;
}

function SlideGlow({ color }: { color: string }) {
  return (
    <div
      className="absolute left-1/2 top-[44%] -translate-x-1/2 -translate-y-1/2 w-[260px] h-[260px] rounded-full blur-2xl -z-10"
      style={{ background: `radial-gradient(circle, ${color}, transparent 70%)` }}
    />
  );
}

function ArcStatSlide({ step }: { step: Extract<Step, { kind: "stat" }> }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-8">
      <SlideGlow color={step.glow} />
      <span className="font-mono text-[10px] tracking-widest uppercase text-cyan-400 mb-3">{step.kicker}</span>
      <span
        className={`font-black tracking-tight leading-none bg-gradient-to-br from-[#a855f7] via-[#e879f9] to-[#ff5db1] bg-clip-text text-transparent ${
          step.small ? "text-4xl" : "text-6xl"
        }`}
        style={{ filter: "drop-shadow(0 0 22px rgba(232,121,249,0.45))" }}
      >
        {step.big}
      </span>
      <p className="mt-4 font-mono text-sm text-gray-400 leading-relaxed max-w-[26ch]">{step.cap}</p>
    </div>
  );
}

function ArcImageSlide({ step }: { step: Extract<Step, { kind: "image" }> }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-8">
      <SlideGlow color={step.glow} />
      <span className="font-mono text-[10px] tracking-widest uppercase text-cyan-400 mb-3">{step.kicker}</span>
      <Image
        src={memeImageUrl(step.imageUrl)}
        alt={step.name}
        width={150}
        height={150}
        unoptimized
        className="w-[150px] h-[150px] object-cover rounded-2xl border-2 border-[#e879f9]/50"
        style={{ boxShadow: "0 20px 50px -12px rgba(232,121,249,0.6)" }}
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
      <SlideGlow color="rgba(168,85,247,0.4)" />
      <div className="absolute top-6 left-6 font-black text-xs tracking-wide">MEMEGPT ARC.</div>
      {stats.tier && (
        <div className="absolute top-5 right-6 font-mono text-[9px] bg-[#a855f7]/20 border border-[#e879f9]/40 rounded-full px-2.5 py-1 whitespace-nowrap">
          {stats.tier.toUpperCase()}
        </div>
      )}
      {stats.period_label && (
        <div className="absolute top-12 left-6 right-6 text-[9.5px] tracking-widest uppercase text-gray-400 text-left">
          {stats.period_label.toUpperCase()}
          {stats.date_span_start && stats.date_span_end && ` · ${formatSpan(stats.date_span_start, stats.date_span_end).toUpperCase()}`}
        </div>
      )}

      <div className="mt-8">
        <span className="text-xl font-black align-top bg-gradient-to-br from-[#a855f7] to-[#e879f9] bg-clip-text text-transparent">
          +
        </span>
        <span
          className="text-5xl font-black tracking-tight bg-gradient-to-br from-[#a855f7] via-[#e879f9] to-[#ff5db1] bg-clip-text text-transparent"
          style={{ filter: "drop-shadow(0 0 22px rgba(232,121,249,0.45))" }}
        >
          {stats.aura.toLocaleString()}
        </span>
        <div className="text-[9px] tracking-[0.3em] text-cyan-400 mt-1">AURA FARMED</div>
      </div>

      <div className="mt-auto w-full font-mono text-[9.5px] text-gray-400 leading-relaxed border-t border-[#a855f7]/20 pt-2.5 text-left space-y-0.5">
        <div>&rsaquo; {stats.total_memes} memes generated</div>
        {top && (
          <div>
            &rsaquo; top: {top.display_name} <span className="text-[#ff5db1]">{top.roast}</span>
          </div>
        )}
        {stats.busiest_time_label && (
          <div>
            &rsaquo; busiest: {stats.busiest_time_label}{" "}
            {stats.hour_roast && <span className="text-[#ff5db1]">{stats.hour_roast}</span>}
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
      <div className="relative max-w-sm w-full rounded-[26px] border border-gray-800/60 bg-[#0b0913] px-8 py-14 text-center overflow-hidden">
        <div
          className="absolute left-1/2 top-[30%] -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] rounded-full blur-3xl -z-0"
          style={{ background: "radial-gradient(circle, rgba(168,85,247,0.35), transparent 70%)" }}
        />
        <div className="relative text-4xl mb-4">🔮</div>
        <h2 className="relative text-xl font-black tracking-tight mb-2">Your arc hasn&apos;t started yet.</h2>
        <p className="relative text-sm text-gray-400 leading-relaxed mb-6 max-w-[40ch] mx-auto">
          Go be unwell somewhere. Five memes minimum before MemeGPT has anything to judge you for.
        </p>
        <div className="relative max-w-[220px] mx-auto mb-6">
          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-[#a855f7] to-[#e879f9]"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-2 font-mono text-[11px] text-gray-600">{totalMemes} / 5 memes toward your first Arc</p>
        </div>
        <Link
          href="/chat"
          className="relative inline-block bg-brand-600 hover:bg-brand-700 transition-colors text-white
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
      <div className="max-w-sm w-full rounded-2xl overflow-hidden border border-gray-800/60 bg-[#13131e] p-3 shadow-lg">
        <Image
          src={memeImageUrl(url)}
          alt="My MemeGPT Arc"
          width={600}
          height={750}
          unoptimized
          className="w-auto h-auto max-w-full max-h-[65vh] object-contain mx-auto rounded-xl"
        />
      </div>
      <ShareButtons memeUrl={url} large />
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
      <div className="relative w-full max-w-[380px] aspect-[3.6/5] rounded-[28px] overflow-hidden border border-gray-800/60 bg-[#0b0913] shadow-2xl shadow-black/60 select-none">
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
          <Link href="/chat" className="text-gray-500 text-base leading-none" title="Exit">
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
            className="w-full py-3 rounded-xl bg-brand-600 hover:bg-brand-700 disabled:opacity-50
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
