"use client";

import { useEffect, useRef, useState } from "react";
import { PixelRevealImage } from "./reveals/PixelRevealImage";

// Real templates, real captions, rendered once ahead of time through the
// actual /chat/ pipeline (not compose_meme()/save_meme() directly — this
// isn't user-generated content, but it is a real Groq round trip through
// segmentation -> RAG -> intent routing -> the Pillow compositor, same as
// a live request). Deliberately spans 20 unrelated contexts (sports,
// movies/TV, music, pop culture, shopping, food, travel, pets, fitness,
// school, weather, gaming, relationships, money, motivation, mood, work,
// internet culture, family, algorithm/internet) rather than one theme —
// an earlier version was 12 cards that were all software-engineering
// in-jokes, which is a bad first impression for a general-audience app.
// About 45% of real generation attempts for this batch came back with a
// picked template but a blank/missing caption (a real, previously-
// unknown reliability gap in intent_router's caption generation for
// certain templates — worth its own investigation, out of scope here);
// each entry below is the first attempt (of up to 3 retries) that
// actually rendered real text.
const HERO_LOOP = [
  { prompt: "when your team blows a 20-point lead in the 4th quarter", image: "/landing/loop_1.png" },
  { prompt: "when someone spoils the finale before you've watched it", image: "/landing/loop_2.png" },
  { prompt: "waiting in line for merch longer than the concert itself", image: "/landing/loop_3.png" },
  { prompt: "when the group chat explodes over one piece of celebrity news", image: "/landing/loop_4.png" },
  { prompt: "adding things to my cart and never actually checking out", image: "/landing/loop_5.png" },
  { prompt: "the last slice of pizza and everyone's too polite to take it", image: "/landing/loop_6.png" },
  { prompt: "when the flight gets delayed for the third time", image: "/landing/loop_7.png" },
  { prompt: "my dog destroyed the couch again", image: "/landing/loop_8.png" },
  { prompt: "day 1 of the gym vs day 2", image: "/landing/loop_9.png" },
  { prompt: "starting the essay the night before it's due", image: "/landing/loop_10.png" },
  { prompt: "when the forecast says sunny and it immediately rains", image: "/landing/loop_11.png" },
  { prompt: "when you finally beat the boss after 20 tries", image: "/landing/loop_12.png" },
  { prompt: "when your friend cancels plans 20 minutes before", image: "/landing/loop_13.png" },
  { prompt: "checking my savings account and immediately regretting it", image: "/landing/loop_14.png" },
  { prompt: "saying I'll start Monday for the fifth Monday in a row", image: "/landing/loop_15.png" },
  { prompt: "trying to fall asleep vs my brain at 3am", image: "/landing/loop_16.png" },
  { prompt: "the meeting that could've been an email", image: "/landing/loop_17.png" },
  { prompt: "the exact moment you realize you replied to the wrong chat", image: "/landing/loop_18.png" },
  { prompt: "meeting your partner's parents for the first time", image: "/landing/loop_19.png" },
  { prompt: "when the algorithm knows me better than my friends do", image: "/landing/loop_20.png" },
];

const IDENTITY_ORDER = HERO_LOOP.map((_, i) => i);

function shuffled(order: number[]): number[] {
  const copy = [...order];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

const TYPE_MS_PER_CHAR = 32;
const PAUSE_AFTER_TYPE_MS = 350;
const THINKING_MS = 750;
const HOLD_MS = 3000;

// How long the card can sit scrolled-out-of-view before coming back
// restarts the current item from scratch instead of just resuming it.
const RESTART_AFTER_HIDDEN_MS = 8000;

type Phase = "typing" | "thinking" | "revealed";

/**
 * The hero's live centerpiece: types a real prompt, pauses on a thinking
 * beat, reveals a real rendered meme, holds, cycles — "the demo is the
 * product" instead of describing the product in prose. Cycles through all
 * 20 real pairs in a random order per page load, looping back once
 * exhausted. Static on the first item's meme under prefers-reduced-motion,
 * no timers running at all in that case.
 *
 * Two things fixed here after real user-reported bugs, not preemptively:
 *
 * 1. Fixed-height stage. The 20 source images range from 700x325 to
 *    600x908 (ratio 2.15 down to 0.66) — with only a min-height, each
 *    phase change actually resized the card and shoved the rest of the
 *    landing page up/down while scrolling. `maxHeightClassName` (a
 *    PixelRevealImage prop added for this) locks the image to this
 *    card's own fixed stage height instead of the viewport-relative
 *    max-h-[65vh] MemeDisplay uses for real chat output — object-contain
 *    still never crops, it just letterboxes consistently now.
 *
 * 2. Pauses when scrolled out of view. An IntersectionObserver gates the
 *    whole scheduling effect on `visible` — no timers get scheduled at
 *    all while off-screen, which freezes progress exactly where it was
 *    (state isn't touched, just un-scheduled) rather than continuing to
 *    advance underneath content the user has scrolled down to read.
 *    Coming back into view resumes from that frozen state if the trip
 *    away was short; if it's been longer than RESTART_AFTER_HIDDEN_MS,
 *    the current item restarts from typing instead of picking up
 *    mid-sequence, since "where it left off" stops being legible after
 *    that long.
 *
 * `order` MUST start as IDENTITY_ORDER (not shuffled) and only randomize
 * inside a useEffect — the initial render happens server-side too, where
 * Math.random() would produce a different sequence than the client's
 * hydration pass and crash with a hydration mismatch. This is the same
 * bug class the old floating-background templates had (see
 * LandingPage.tsx) — fixed the same way there: nothing Math.random()-
 * derived is computed before mount.
 */
export function HeroLoop() {
  const containerRef = useRef<HTMLDivElement>(null);
  const hiddenAtRef = useRef<number | null>(null);
  const typedRef = useRef("");

  const [reduced, setReduced] = useState(false);
  const [order, setOrder] = useState<number[]>(IDENTITY_ORDER);
  const [position, setPosition] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const [typed, setTyped] = useState("");
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setReduced(true);
    } else {
      setOrder(shuffled(IDENTITY_ORDER));
    }
  }, []);

  // Scroll visibility — pause while off-screen, restart-or-resume on return.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), {
      threshold: 0,
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    typedRef.current = typed;
  }, [typed]);

  useEffect(() => {
    if (!visible) {
      hiddenAtRef.current = Date.now();
      return;
    }
    const hiddenAt = hiddenAtRef.current;
    hiddenAtRef.current = null;
    if (hiddenAt !== null && Date.now() - hiddenAt > RESTART_AFTER_HIDDEN_MS) {
      // Update the ref synchronously, not just via state — this effect and
      // the scheduling effect below both run in the same commit once
      // `visible` flips true, and the scheduling effect reads
      // typedRef.current to decide where to resume from. If that read
      // happened before this component's re-render had a chance to sync
      // the ref to the new (reset) `typed` state, the resume logic would
      // see the STALE pre-restart progress and silently resume instead of
      // restarting — confirmed live: the restart branch never visibly
      // took effect without this line, every "long absence" case still
      // resumed mid-word instead of restarting.
      typedRef.current = "";
      setTyped("");
      setPhase("typing");
    }
  }, [visible]);

  useEffect(() => {
    if (reduced) {
      setPhase("revealed");
      setTyped(HERO_LOOP[order[0]].prompt);
      return;
    }

    if (!visible) return; // paused — resumes when visible flips back true

    const current = HERO_LOOP[order[position % order.length]];
    const timers: ReturnType<typeof setTimeout>[] = [];

    if (phase === "typing") {
      // Resume from wherever typing had gotten to (e.g. paused mid-word by
      // scrolling away and back) rather than restarting the animation —
      // only valid if the frozen text is actually a prefix of this item's
      // prompt (a fresh cycle already reset typed to "" before this runs,
      // so i=0 falls out naturally in that case too).
      let i = current.prompt.startsWith(typedRef.current) ? typedRef.current.length : 0;
      if (i > 0) setTyped(current.prompt.slice(0, i));
      const tick = () => {
        i += 1;
        setTyped(current.prompt.slice(0, i));
        if (i < current.prompt.length) {
          timers.push(setTimeout(tick, TYPE_MS_PER_CHAR));
        } else {
          timers.push(setTimeout(() => setPhase("thinking"), PAUSE_AFTER_TYPE_MS));
        }
      };
      timers.push(setTimeout(tick, TYPE_MS_PER_CHAR));
    } else if (phase === "thinking") {
      timers.push(setTimeout(() => setPhase("revealed"), THINKING_MS));
    } else if (phase === "revealed") {
      timers.push(
        setTimeout(() => {
          setTyped("");
          setPosition((p) => p + 1);
          setPhase("typing");
        }, HOLD_MS)
      );
    }

    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, position, order, reduced, visible]);

  const item = HERO_LOOP[order[position % order.length]];

  return (
    <div
      ref={containerRef}
      className="w-full max-w-xs sm:max-w-sm rounded-2xl bg-card border border-border p-4 shadow-2xl shadow-black/50"
    >
      <div className="h-14 flex items-start overflow-hidden">
        <p className="text-sm text-gray-300 leading-snug">
          {typed}
          {!reduced && phase === "typing" && (
            <span className="inline-block w-[2px] h-[1em] bg-gray-500 ml-0.5 align-middle animate-pulse" />
          )}
        </p>
      </div>

      <div className="mt-3 h-56 flex items-center justify-center">
        {phase === "thinking" && !reduced ? (
          <div className="thinking-orb" aria-hidden />
        ) : phase === "revealed" || reduced ? (
          <PixelRevealImage
            key={item.image}
            src={item.image}
            alt={`Meme generated from: ${item.prompt}`}
            className="rounded-xl overflow-hidden"
            maxHeightClassName="max-h-56"
          />
        ) : null}
      </div>
    </div>
  );
}
