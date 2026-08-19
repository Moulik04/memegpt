"use client";

import { useEffect, useState } from "react";
import { PixelRevealImage } from "./reveals/PixelRevealImage";

// Real templates, real captions, rendered once ahead of time the same way
// drake_example.png was (Pillow, not compose_meme()/save_meme() — this
// isn't user-generated content) — see git history for the render scripts.
// Prompts are drawn straight from lib/examplePrompts.ts's pool (or written
// in the same voice) so it matches what Chat's own empty state shows.
const HERO_LOOP = [
  { prompt: "when you push straight to main by accident", image: "/landing/loop_1.png" },
  { prompt: "waiting for my PR to get reviewed for 3 days", image: "/landing/loop_2.png" },
  { prompt: "when the deploy finally works on first try", image: "/landing/loop_3.png" },
  { prompt: "when the bug only happens in production", image: "/landing/loop_4.png" },
  { prompt: "my resume vs my actual daily tasks", image: "/landing/loop_5.png" },
  { prompt: "my manager asking who broke production", image: "/landing/loop_6.png" },
  { prompt: "when the standup goes 45 minutes over", image: "/landing/loop_7.png" },
  { prompt: "explaining to my non-tech friends what I do for a living", image: "/landing/loop_8.png" },
  { prompt: "when someone says 'quick call' and it's 90 minutes", image: "/landing/loop_9.png" },
  { prompt: "when the CI pipeline fails on the one thing you didn't touch", image: "/landing/loop_10.png" },
  { prompt: "when a new framework drops the week before a deadline", image: "/landing/loop_11.png" },
  { prompt: "my hottest take on tabs vs spaces", image: "/landing/loop_12.png" },
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

type Phase = "typing" | "thinking" | "revealed";

/**
 * The hero's live centerpiece: types a real prompt, pauses on a thinking
 * beat, reveals a real rendered meme, holds, cycles to the next — "the
 * demo is the product" instead of describing the product in prose. Cycles
 * through all 12 real pairs in a random order per page load, looping back
 * once exhausted. Static on the first item's meme under
 * prefers-reduced-motion, no timers running at all in that case.
 *
 * `order` MUST start as IDENTITY_ORDER (not shuffled) and only randomize
 * inside a useEffect — same reasoning as `reduced` below: the initial
 * render happens server-side too, where Math.random() would produce a
 * different sequence than the client's hydration pass and crash with a
 * hydration mismatch. This is the same bug class the old floating-
 * background templates had (see LandingPage.tsx) — fixed the same way
 * there: nothing Math.random()-derived is computed before mount.
 */
export function HeroLoop() {
  const [reduced, setReduced] = useState(false);
  const [order, setOrder] = useState<number[]>(IDENTITY_ORDER);
  const [position, setPosition] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setReduced(true);
    } else {
      setOrder(shuffled(IDENTITY_ORDER));
    }
  }, []);

  useEffect(() => {
    const item = HERO_LOOP[order[0]];

    if (reduced) {
      setPhase("revealed");
      setTyped(item.prompt);
      return;
    }

    const current = HERO_LOOP[order[position % order.length]];
    const timers: ReturnType<typeof setTimeout>[] = [];

    if (phase === "typing") {
      let i = 0;
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
  }, [phase, position, order, reduced]);

  const item = HERO_LOOP[order[position % order.length]];

  return (
    <div className="w-full max-w-xs sm:max-w-sm rounded-2xl bg-card border border-border p-4 shadow-2xl shadow-black/50">
      <div className="min-h-[3.5rem] flex items-start">
        <p className="text-sm text-gray-300 leading-snug">
          {typed}
          {!reduced && phase === "typing" && (
            <span className="inline-block w-[2px] h-[1em] bg-gray-500 ml-0.5 align-middle animate-pulse" />
          )}
        </p>
      </div>

      <div className="mt-3 min-h-[180px] flex items-center justify-center">
        {phase === "thinking" && !reduced ? (
          <div className="thinking-orb" aria-hidden />
        ) : phase === "revealed" || reduced ? (
          <PixelRevealImage
            key={item.image}
            src={item.image}
            alt={`Meme generated from: ${item.prompt}`}
            className="rounded-xl overflow-hidden"
          />
        ) : null}
      </div>
    </div>
  );
}
