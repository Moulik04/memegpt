"use client";

import Link from "next/link";
import Image from "next/image";
import { motion } from "motion/react";

interface FloatCard {
  src: string;
  alt: string;
  className: string;
  rotate: number;
  duration: number;
  delay: number;
}

const FLOAT_CARDS: FloatCard[] = [
  { src: "/landing/drake.jpg", alt: "Drake meme template", className: "left-[3%] top-[12%] w-24 sm:w-32", rotate: -8, duration: 6, delay: 0 },
  { src: "/landing/woman_yelling_at_cat.jpg", alt: "Woman yelling at cat meme template", className: "right-[4%] top-[8%] w-28 sm:w-36", rotate: 6, duration: 7, delay: 0.4 },
  { src: "/landing/hide_the_pain_harold.jpg", alt: "Hide the pain Harold meme template", className: "left-[10%] bottom-[14%] w-20 sm:w-28", rotate: 5, duration: 6.5, delay: 0.8 },
  { src: "/landing/two_buttons.jpg", alt: "Two buttons meme template", className: "right-[10%] bottom-[10%] w-24 sm:w-32", rotate: -6, duration: 5.5, delay: 0.2 },
  { src: "/landing/this_is_fine.jpg", alt: "This is fine meme template", className: "left-[22%] top-[4%] w-16 sm:w-24 hidden sm:block", rotate: -4, duration: 7.5, delay: 1.1 },
  { src: "/landing/surprised_pikachu.jpg", alt: "Surprised Pikachu meme template", className: "right-[22%] bottom-[4%] w-16 sm:w-24 hidden sm:block", rotate: 8, duration: 6.2, delay: 0.6 },
];

const STEPS = [
  {
    title: "Tell it what is going on",
    body: "Type a message, paste a whole group chat, or drop in a screenshot. Whatever mood you are in, that is the input.",
  },
  {
    title: "It reads the room",
    body: "An AI matches your situation against a library of over a hundred meme templates and picks the one that actually fits.",
  },
  {
    title: "Get your meme",
    body: "Captioned, rendered, and ready to share in a few seconds. No template hunting, no font wrangling.",
  },
];

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0 },
};

export function LandingPage() {
  return (
    <div className="relative min-h-dvh overflow-x-hidden bg-gray-950">
      {/* Ambient background blobs */}
      <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
        <motion.div
          className="absolute -top-40 -left-40 h-96 w-96 rounded-full bg-brand-600/20 blur-[100px]"
          animate={{ x: [0, 40, 0], y: [0, 30, 0] }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute top-1/3 -right-40 h-96 w-96 rounded-full bg-pink-600/10 blur-[100px]"
          animate={{ x: [0, -30, 0], y: [0, 40, 0] }}
          transition={{ duration: 22, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute bottom-0 left-1/3 h-96 w-96 rounded-full bg-brand-500/10 blur-[100px]"
          animate={{ x: [0, 30, 0], y: [0, -20, 0] }}
          transition={{ duration: 20, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>

      {/* Nav */}
      <motion.header
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="relative z-20 flex items-center justify-between px-6 py-5 sm:px-10"
      >
        <span className="text-xl font-extrabold tracking-tight gradient-text">MemeGPT</span>
        <Link
          href="/chat"
          className="rounded-full bg-white/5 border border-gray-800 px-4 py-2 text-sm text-gray-300
                     hover:border-brand-500/60 hover:text-white transition-colors"
        >
          Open the app
        </Link>
      </motion.header>

      {/* Hero */}
      <section className="relative z-10 px-6 pt-16 pb-28 sm:pt-24 sm:pb-36">
        <div aria-hidden className="absolute inset-0 -z-10">
          {FLOAT_CARDS.map((card) => (
            <motion.div
              key={card.src}
              className={`absolute ${card.className} rounded-xl overflow-hidden border border-white/10
                         shadow-2xl shadow-black/50 opacity-60 sm:opacity-80`}
              initial={{ opacity: 0, rotate: card.rotate, y: 10 }}
              animate={{
                opacity: [0, 0.8, 0.8],
                y: [10, -14, 10],
                rotate: [card.rotate, card.rotate + 3, card.rotate],
              }}
              transition={{
                opacity: { duration: 1, delay: card.delay },
                y: { duration: card.duration, repeat: Infinity, ease: "easeInOut", delay: card.delay },
                rotate: { duration: card.duration, repeat: Infinity, ease: "easeInOut", delay: card.delay },
              }}
            >
              <Image src={card.src} alt={card.alt} width={200} height={200} className="w-full h-auto" />
            </motion.div>
          ))}
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
            <span className="gradient-text">speaks meme.</span>
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
              className="w-full sm:w-auto bg-brand-600 hover:bg-brand-500 transition-colors
                         text-white font-semibold rounded-full px-8 py-3.5 text-base
                         shadow-lg shadow-brand-900/40"
            >
              Start chatting
            </Link>
            <Link
              href="/lore"
              className="w-full sm:w-auto bg-white/5 hover:bg-white/10 border border-gray-800
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
          <h2 className="text-2xl sm:text-4xl font-bold tracking-tight">How it actually works</h2>
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
              className="rounded-2xl bg-[#13131e] border border-gray-800/60 p-6"
            >
              <div className="w-9 h-9 rounded-full bg-brand-600/20 text-brand-400 font-bold
                             flex items-center justify-center text-sm mb-4">
                {i + 1}
              </div>
              <h3 className="font-semibold text-gray-100 mb-2">{step.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{step.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Two modes */}
      <section className="relative z-10 px-6 py-20 sm:py-28">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={fadeUp}
          transition={{ duration: 0.6 }}
          className="max-w-2xl mx-auto text-center mb-16"
        >
          <h2 className="text-2xl sm:text-4xl font-bold tracking-tight">Two ways to use it</h2>
          <p className="mt-3 text-gray-500">Same brain underneath, different amount of chaos.</p>
        </motion.div>

        <div className="max-w-4xl mx-auto grid gap-6 sm:grid-cols-2">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-60px" }}
            variants={fadeUp}
            transition={{ duration: 0.6 }}
            className="rounded-2xl bg-gradient-to-br from-brand-900/40 to-[#13131e] border border-brand-800/40 p-8"
          >
            <span className="text-xs font-semibold text-brand-400 uppercase tracking-wide">Chat</span>
            <h3 className="text-xl font-bold mt-2 mb-3">Talk to it like any chatbot</h3>
            <p className="text-sm text-gray-400 leading-relaxed">
              Type a thought, attach a photo if you want, and get a meme back.
              The catch is it never breaks character. It only replies in memes.
            </p>
          </motion.div>

          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, margin: "-60px" }}
            variants={fadeUp}
            transition={{ duration: 0.6, delay: 0.12 }}
            className="rounded-2xl bg-gradient-to-br from-pink-900/30 to-[#13131e] border border-pink-800/30 p-8"
          >
            <span className="text-xs font-semibold text-pink-400 uppercase tracking-wide">Lore</span>
            <h3 className="text-xl font-bold mt-2 mb-3">Drop in the whole story</h3>
            <p className="text-sm text-gray-400 leading-relaxed">
              Paste a whole group chat or upload a stack of screenshots. Get
              back several memes, one for every moment worth remembering.
            </p>
          </motion.div>
        </div>
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
            Ready to see what it makes of your day?
          </h2>
          <Link
            href="/chat"
            className="inline-block mt-8 bg-brand-600 hover:bg-brand-500 transition-colors
                       text-white font-semibold rounded-full px-8 py-3.5 text-base
                       shadow-lg shadow-brand-900/40"
          >
            Open MemeGPT
          </Link>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 px-6 py-10 border-t border-gray-900">
        <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-gray-600">
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
    </div>
  );
}
