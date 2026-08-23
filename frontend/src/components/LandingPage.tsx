"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { motion } from "motion/react";
import { AuthControl } from "@/components/AuthControl";
import { HeroLoop } from "@/components/HeroLoop";
import { templateLabel } from "@/lib/utils";

// Every image here is a real template MemeGPT can actually pick for you.
// A random 6 fill the hero's floating slots on each page load, drawn
// fresh from this pool instead of always showing the same six. Ambient
// texture around HeroLoop's live centerpiece, not competing with it —
// raw uncaptioned templates read as decoration, not as "the demo".
const FLOAT_POOL = [
  "drake", "woman_yelling_at_cat", "hide_the_pain_harold", "two_buttons", "this_is_fine",
  "surprised_pikachu", "distracted_boyfriend", "buff_doge_vs_cheems", "expanding_brain",
  "mocking_spongebob", "change_my_mind", "epic_handshake", "batman_slapping_robin",
  "evil_kermit", "disaster_girl", "chill_guy", "disappointed_black_guy", "futurama_fry",
  "ancient_aliens", "flex_tape", "always_has_been", "boardroom_meeting_suggestion",
  "bell_curve", "drunk_friend_caught", "mr_incredible_uncanny", "panik_kalm_panik",
  "is_this_a_pigeon", "one_does_not_simply", "trade_offer", "oprah", "monkey_puppet",
  "kiss_cam_caught",
];

function templateSrc(id: string) {
  const png = new Set(["buff_doge_vs_cheems", "chill_guy", "flex_tape", "always_has_been", "bell_curve", "drunk_friend_caught", "mr_incredible_uncanny", "panik_kalm_panik", "kiss_cam_caught"]);
  return `/landing/${id}.${png.has(id) ? "png" : "jpg"}`;
}

function pickRandomTemplates(count: number): string[] {
  const shuffled = [...FLOAT_POOL];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled.slice(0, count);
}

// Fixed positions and motion timing, the actual image in each slot is
// randomized per page load (see pickRandomTemplates above).
const FLOAT_SLOTS = [
  { className: "left-[3%] top-[12%] w-24 sm:w-32", rotate: -8, duration: 6, delay: 0 },
  { className: "right-[4%] top-[8%] w-28 sm:w-36", rotate: 6, duration: 7, delay: 0.4 },
  { className: "left-[10%] bottom-[14%] w-20 sm:w-28", rotate: 5, duration: 6.5, delay: 0.8 },
  { className: "right-[10%] bottom-[10%] w-24 sm:w-32", rotate: -6, duration: 5.5, delay: 0.2 },
  { className: "left-[22%] top-[4%] w-16 sm:w-24 hidden sm:block", rotate: -4, duration: 7.5, delay: 1.1 },
  { className: "right-[22%] bottom-[4%] w-16 sm:w-24 hidden sm:block", rotate: 8, duration: 6.2, delay: 0.6 },
];

const STEPS = [
  {
    title: "Tell MemeGPT what's going on",
    body: "Type a message, paste a whole group chat, or drop in a screenshot. Whatever mood you are in, that is the input.",
  },
  {
    title: "MemeGPT reads the room",
    body: "An AI matches your situation against a library of over a hundred meme templates and picks the one that actually fits.",
  },
  {
    title: "Get your meme",
    body: "Captioned, rendered, and ready to share in a few seconds. No template hunting, no font wrangling.",
  },
];

const MODES = [
  {
    label: "Chat",
    title: "Talk to MemeGPT like any chatbot",
    body: "Type a thought, attach a photo if you want, and get a meme back. MemeGPT never breaks character, every reply comes back as a meme.",
  },
  {
    label: "Lore",
    title: "Drop in the whole story",
    body: "Paste a whole group chat or upload a stack of screenshots. Get back several memes, one for every moment worth remembering.",
  },
  {
    label: "Make",
    title: "Pick the template yourself",
    body: "Skip the AI's judgment entirely. Search the full template library, write your own captions box by box, and render it exactly your way.",
  },
  {
    label: "Arc",
    title: "See your meme era",
    body: "Your most-summoned template, your longest streak, an aura score that goes up whether you like it or not. Roast copy included, free of charge.",
  },
];

const FAQS = [
  {
    q: "Is MemeGPT free?",
    a: "Yes. Every surface works without signing in — no email, no account. Signing in only adds saved history for Chat and Lore across devices.",
  },
  {
    q: "What's the difference between Chat, Lore, and Make?",
    a: "Chat is a normal back-and-forth, one meme per reply. Lore is for big dumps — paste a whole group chat or a stack of screenshots and get several memes back at once. Make skips the AI's judgment entirely: you pick the template and write the captions yourself.",
  },
  {
    q: "What if it picks the wrong template?",
    a: "Thumbs it down. Every reply has feedback buttons, and MemeGPT learns from what actually lands over time.",
  },
  {
    q: "Can I upload photos or screenshots?",
    a: "Yes, in both Chat and Lore. Attach one photo in Chat, or a whole stack in Lore — MemeGPT reads what's in them the same way it reads text.",
  },
  {
    q: "Does it work on my phone?",
    a: "Yes — it's a full mobile site, and you can add it to your home screen for an app-like experience. (Android also lets you share a screenshot straight from Photos into Lore.)",
  },
];

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0 },
};

export function LandingPage() {
  // Starts empty (matches server render exactly) and only fills in after
  // mount — Math.random() during the initial render disagrees between
  // server and client, which is a real hydration-mismatch crash, not a
  // theoretical one (see HeroLoop.tsx's comment for the same fix applied
  // to its shuffle). No floats is a fine, brief first paint; wrong floats
  // that then swap out from under the user is not.
  const [floatIds, setFloatIds] = useState<string[]>([]);
  useEffect(() => {
    // The infinite drift/rotate loop on these is purely decorative — no
    // MotionConfig wraps this app to auto-gate Motion's animations on
    // prefers-reduced-motion, so skip populating them at all rather than
    // ship a non-essential animation reduced-motion users asked to avoid.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    setFloatIds(pickRandomTemplates(FLOAT_SLOTS.length));
  }, []);

  return (
    <div className="relative min-h-dvh overflow-x-hidden bg-background">
      {/* Nav */}
      <motion.header
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="relative z-20 flex items-center justify-between px-6 py-5 sm:px-10"
      >
        <span className="caption caption-mark text-xl">MemeGPT</span>
        <div className="flex items-center gap-4">
          <AuthControl />
          <Link
            href="/chat"
            className="rounded-full bg-white/5 border border-border px-4 py-2 text-sm text-gray-300
                       hover:border-accent/60 hover:text-white transition-colors"
          >
            Open the app
          </Link>
        </div>
      </motion.header>

      {/* Hero */}
      <section className="relative z-10 px-6 pt-16 pb-28 sm:pt-24 sm:pb-36">
        <div aria-hidden className="absolute inset-0 -z-10">
          {FLOAT_SLOTS.map((slot, i) => {
            const id = floatIds[i];
            if (!id) return null;
            return (
              <motion.div
                key={id}
                className={`absolute ${slot.className} rounded-xl overflow-hidden border border-white/10
                           shadow-2xl shadow-black/50 opacity-60 sm:opacity-80`}
                initial={{ opacity: 0, rotate: slot.rotate, y: 10 }}
                animate={{
                  opacity: [0, 0.8, 0.8],
                  y: [10, -14, 10],
                  rotate: [slot.rotate, slot.rotate + 3, slot.rotate],
                }}
                transition={{
                  opacity: { duration: 1, delay: slot.delay },
                  y: { duration: slot.duration, repeat: Infinity, ease: "easeInOut", delay: slot.delay },
                  rotate: { duration: slot.duration, repeat: Infinity, ease: "easeInOut", delay: slot.delay },
                }}
              >
                <Image
                  src={templateSrc(id)}
                  alt={`${templateLabel(id)} meme template`}
                  width={200}
                  height={200}
                  className="w-full h-auto"
                />
              </motion.div>
            );
          })}
        </div>

        <div className="max-w-2xl mx-auto text-center">
          <motion.h1
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ duration: 0.7, delay: 0.1 }}
            className="text-4xl sm:text-6xl font-extrabold tracking-tight leading-[1.05]"
          >
            A chatbot that only
            <br />
            <span className="caption text-4xl sm:text-6xl">speaks meme.</span>
          </motion.h1>

          <motion.p
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ duration: 0.7, delay: 0.25 }}
            className="mt-6 text-base sm:text-lg text-gray-400 leading-relaxed"
          >
            Say what is on your mind, or paste a whole conversation. MemeGPT
            figures out the moment and hands you back the meme that actually
            fits, captioned and ready to send.
          </motion.p>

          <motion.div
            initial="hidden"
            animate="visible"
            variants={fadeUp}
            transition={{ duration: 0.7, delay: 0.4 }}
            className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3"
          >
            <Link
              href="/chat"
              className="w-full sm:w-auto bg-accent hover:bg-accent/90 transition-colors
                         text-white font-semibold rounded-full px-8 py-3.5 text-base
                         shadow-lg"
            >
              Start chatting
            </Link>
            <Link
              href="/lore"
              className="w-full sm:w-auto bg-white/5 hover:bg-white/10 border border-border
                         hover:border-gray-700 transition-colors text-gray-200 font-semibold
                         rounded-full px-8 py-3.5 text-base"
            >
              Try Lore mode
            </Link>
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.6 }}
            className="mt-5 text-xs text-gray-600"
          >
            No sign up. No email. Just start typing.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.75 }}
            className="mt-14 flex flex-col items-center gap-3"
          >
            <span className="text-xs text-gray-600 uppercase tracking-wide">
              watch it happen
            </span>
            <HeroLoop />
          </motion.div>
        </div>
      </section>

      {/* How it works */}
      <section className="relative z-10 px-6 py-20 sm:py-28">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={fadeUp}
          transition={{ duration: 0.6 }}
          className="max-w-2xl mx-auto text-center mb-16"
        >
          <h2 className="text-2xl sm:text-4xl font-bold tracking-tight">How MemeGPT actually works</h2>
          <p className="mt-3 text-gray-500">Three steps. No template scrolling required.</p>
        </motion.div>

        <div className="max-w-4xl mx-auto grid gap-6 sm:grid-cols-3">
          {STEPS.map((step, i) => (
            <motion.div
              key={step.title}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true, margin: "-60px" }}
              variants={fadeUp}
              transition={{ duration: 0.6, delay: i * 0.12 }}
              className="rounded-2xl bg-card border border-border p-6 transition-all duration-200
                         hover:border-gray-700 hover:shadow-lg hover:-translate-y-0.5"
            >
              <div className="w-9 h-9 rounded-full bg-accent/20 text-accent font-bold
                             flex items-center justify-center text-sm mb-4">
                {i + 1}
              </div>
              <h3 className="font-semibold text-gray-100 mb-2">{step.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{step.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Four modes */}
      <section className="relative z-10 px-6 py-20 sm:py-28">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={fadeUp}
          transition={{ duration: 0.6 }}
          className="max-w-2xl mx-auto text-center mb-16"
        >
          <h2 className="text-2xl sm:text-4xl font-bold tracking-tight">Four ways to use MemeGPT</h2>
          <p className="mt-3 text-gray-500">Same brain underneath, different amount of control.</p>
        </motion.div>

        <div className="max-w-4xl mx-auto grid gap-6 sm:grid-cols-2">
          {MODES.map((mode, i) => (
            <motion.div
              key={mode.label}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true, margin: "-60px" }}
              variants={fadeUp}
              transition={{ duration: 0.6, delay: i * 0.1 }}
              className="rounded-2xl bg-card border border-border p-8 transition-all duration-200
                         hover:border-gray-700 hover:shadow-lg hover:-translate-y-0.5"
            >
              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{mode.label}</span>
              <h3 className="text-xl font-bold mt-2 mb-3">{mode.title}</h3>
              <p className="text-sm text-gray-400 leading-relaxed">{mode.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section className="relative z-10 px-6 py-20 sm:py-28">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={fadeUp}
          transition={{ duration: 0.6 }}
          className="max-w-2xl mx-auto text-center mb-12"
        >
          <h2 className="text-2xl sm:text-4xl font-bold tracking-tight">Questions, answered</h2>
        </motion.div>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={fadeUp}
          transition={{ duration: 0.6 }}
          className="max-w-2xl mx-auto flex flex-col gap-3"
        >
          {FAQS.map((item) => (
            <details
              key={item.q}
              className="group rounded-2xl bg-card border border-border p-5 transition-colors
                         hover:border-gray-700 open:border-gray-700"
            >
              <summary className="flex items-center justify-between gap-4 cursor-pointer list-none
                                   font-semibold text-gray-100">
                {item.q}
                <span className="shrink-0 text-gray-500 transition-transform duration-200 group-open:rotate-45">
                  +
                </span>
              </summary>
              <p className="mt-3 text-sm text-gray-400 leading-relaxed">{item.a}</p>
            </details>
          ))}
        </motion.div>
      </section>

      {/* Final CTA */}
      <section className="relative z-10 px-6 py-24 sm:py-32">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={fadeUp}
          transition={{ duration: 0.7 }}
          className="max-w-xl mx-auto text-center"
        >
          <h2 className="text-2xl sm:text-4xl font-bold tracking-tight">
            Ready to see what MemeGPT makes of your day?
          </h2>
          <Link
            href="/chat"
            className="inline-block mt-8 bg-accent hover:bg-accent/90 transition-colors
                       text-white font-semibold rounded-full px-8 py-3.5 text-base
                       shadow-lg"
          >
            Open MemeGPT
          </Link>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 px-6 py-10 pb-24 sm:pb-10 border-t border-border">
        <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-5 text-xs text-gray-600">
          <nav className="flex items-center gap-4">
            <Link href="/chat" className="hover:text-gray-400 transition-colors">Chat</Link>
            <Link href="/lore" className="hover:text-gray-400 transition-colors">Lore</Link>
            <Link href="/make" className="hover:text-gray-400 transition-colors">Make</Link>
            <Link href="/arc" className="hover:text-gray-400 transition-colors">Arc</Link>
            <Link href="/privacy" className="hover:text-gray-400 transition-colors">Privacy</Link>
          </nav>
          <span>MemeGPT. Built for fun, not for profit.</span>
          <a
            href="https://github.com/Moulik04/memegpt"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-gray-400 transition-colors"
          >
            View source on GitHub
          </a>
        </div>
      </footer>

      {/* Sticky mobile CTA */}
      <div
        className="sm:hidden fixed bottom-0 inset-x-0 z-30 border-t border-border
                   bg-background/95 backdrop-blur-sm px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]"
      >
        <Link
          href="/chat"
          className="block w-full text-center bg-accent hover:bg-accent/90 transition-colors
                     text-white font-semibold rounded-full px-8 py-3 text-base shadow-lg"
        >
          Start chatting
        </Link>
      </div>
    </div>
  );
}
