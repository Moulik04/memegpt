"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { FAST_OUT, FAST_SETTLE, INSTANT, SETTLE } from "@/lib/motion";
import { Masthead } from "@/components/Masthead";
import { MobileNav } from "@/components/MobileNav";
import { MemeDisplay } from "@/components/MemeDisplay";
import { handToChat } from "@/lib/landingHandoff";
import { MAX_IMAGE_BYTES, MAX_IMAGES_PER_MESSAGE, PICK_TOO_LARGE, PICK_TOO_MANY, PICK_UNSUPPORTED } from "@/lib/notices";
import { allSupportedImages } from "@/lib/imageFormat";

/** The copy deck, section 7.1. */
const HEADLINE = "The group chat has a front page.";
const SUBLINE = "Say what happened, paste the group chat or add a screenshot. MemeGPT sends back the meme.";
const NEXT_STORY = "Next story";

/**
 * Real prompts and the memes MemeGPT made for them, rendered through the
 * full /chat/ pipeline. Sizes are the files' own, so the lead slot never
 * guesses an image's shape.
 */
const LEAD_STORIES = [
  { prompt: "when your team blows a 20-point lead in the 4th quarter", image: "/landing/loop_1.png", w: 580, h: 282 },
  { prompt: "when someone spoils the finale before you've watched it", image: "/landing/loop_2.png", w: 1893, h: 1892 },
  { prompt: "waiting in line for merch longer than the concert itself", image: "/landing/loop_3.png", w: 298, h: 403 },
  { prompt: "when the group chat explodes over one piece of celebrity news", image: "/landing/loop_4.png", w: 680, h: 438 },
  { prompt: "adding things to my cart and never actually checking out", image: "/landing/loop_5.png", w: 1200, h: 1200 },
  { prompt: "the last slice of pizza and everyone's too polite to take it", image: "/landing/loop_6.png", w: 600, h: 908 },
  { prompt: "when the flight gets delayed for the third time", image: "/landing/loop_7.png", w: 1235, h: 695 },
  { prompt: "my dog destroyed the couch again", image: "/landing/loop_8.png", w: 1235, h: 695 },
  { prompt: "day 1 of the gym vs day 2", image: "/landing/loop_9.png", w: 937, h: 720 },
  { prompt: "starting the essay the night before it's due", image: "/landing/loop_10.png", w: 640, h: 881 },
  { prompt: "when the forecast says sunny and it immediately rains", image: "/landing/loop_11.png", w: 1893, h: 1892 },
  { prompt: "when you finally beat the boss after 20 tries", image: "/landing/loop_12.png", w: 640, h: 881 },
  { prompt: "when your friend cancels plans 20 minutes before", image: "/landing/loop_13.png", w: 1893, h: 1892 },
  { prompt: "checking my savings account and immediately regretting it", image: "/landing/loop_14.png", w: 1893, h: 1892 },
  { prompt: "saying I'll start Monday for the fifth Monday in a row", image: "/landing/loop_15.png", w: 619, h: 403 },
  { prompt: "trying to fall asleep vs my brain at 3am", image: "/landing/loop_16.png", w: 700, h: 325 },
  { prompt: "the meeting that could've been an email", image: "/landing/loop_17.png", w: 1200, h: 1200 },
  { prompt: "the exact moment you realize you replied to the wrong chat", image: "/landing/loop_18.png", w: 1893, h: 1892 },
  { prompt: "meeting your partner's parents for the first time", image: "/landing/loop_19.png", w: 782, h: 1032 },
  { prompt: "when the algorithm knows me better than my friends do", image: "/landing/loop_20.png", w: 857, h: 1202 },
];

// Shuffled once per visit and kept for it, like Make's library: coming
// back to the landing page carries on through the same order.
let leadOrder: number[] | null = null;
function visitOrder(): number[] {
  if (!leadOrder) {
    const order = LEAD_STORIES.map((_, i) => i);
    for (let i = order.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [order[i], order[j]] = [order[j], order[i]];
    }
    leadOrder = order;
  }
  return leadOrder;
}
let leadPosition = 0;

/** The copy deck, section 7.3: the shared group chat, one message a line. */
const SHARED_CHAT = [
  "Maya: Flight delayed again. Third time.",
  "Leo: That gate has your mail now.",
  "June: This meeting could've been an email.",
  "You: It has a follow-up meeting.",
  "Leo: Do we get an agenda?",
  "June: I haven't started the essay.",
  "You: It's due tomorrow. Opening the doc at 11:58.",
  "Maya: Phone's at 1%.",
  "Leo: You sent that with one percent?",
  "Maya: I'm committed to the bit.",
];

/**
 * Real Lore renders of the shared chat, each with the 1-based lines the
 * backend returned as its source. Empty until those renders exist; the Lore
 * story stays off the page until then rather than showing a stand-in.
 */
const LORE_EXAMPLES: { image: string; w: number; h: number; lines: number[] }[] = [];

const STORY_KICKER = "border-t-2 border-foreground pt-2 text-sm font-bold uppercase tracking-wide text-foreground";
const STORY_LINK =
  "inline-flex items-center min-h-11 text-base font-medium text-foreground underline decoration-brand " +
  "decoration-2 underline-offset-4 hover:decoration-[3px]";
const STORY_IMAGE_HEIGHT = "max-h-[60vh] md:max-h-[30rem]";

const FACTS = [
  "120+ meme templates, including a few animated GIFs.",
  "Every part works without an account.",
  "Google sign-in saves Chat and Lore history across devices.",
  "Original photos are never kept.",
  "Signed out, your text isn't kept either. Only the memes MemeGPT makes are.",
  "Forget me erases your anonymous identity, history and memes.",
  "Thumbs up or down teaches MemeGPT your sense of humor.",
  "Works on phones and installs like an app.",
  "There's a Discord bot: /meme.",
];

const FAQS = [
  {
    q: "Is MemeGPT free?",
    a: "Yes. Every part works without signing in: no email, no account. Signing in only adds saved Chat and Lore history across devices.",
  },
  {
    q: "What's the difference between Chat, Lore and Make?",
    a: "Chat is a normal back-and-forth, usually one meme per reply. Lore is for big dumps: paste a whole group chat or a stack of screenshots and get several memes back at once. Make skips the AI's judgment: you pick the template and write the captions.",
  },
  {
    q: "What if it picks the wrong template?",
    a: "Thumbs it down. Every reply has feedback buttons, and MemeGPT learns from what actually lands.",
  },
  {
    q: "Can I upload photos or screenshots?",
    a: "Yes. Attach up to six at a time in Chat or Lore. MemeGPT reads what's in them the same way it reads text.",
  },
  {
    q: "Does it work on my phone?",
    a: "Yes. It's a full mobile site, and you can add it to your home screen. On Android you can share a screenshot straight from Photos into Lore.",
  },
];

const GITHUB_URL = "https://github.com/Moulik04/memegpt";

export function LandingPage() {
  return (
    <div className="min-h-dvh bg-background pb-[calc(3rem+1px+env(safe-area-inset-bottom))] md:pb-0">
      <Masthead variant="landing" />
      <main>
        <Cover />
        <div className="mx-auto max-w-6xl px-4 md:px-8">
          <ChatStory />
          {LORE_EXAMPLES.length > 0 && <LoreStory />}
          <MakeStory />
          <ArcStory />
          <InBrief />
          <section aria-label="Make a meme" className="py-12 md:py-16 border-t-2 border-foreground">
            <Composer />
          </section>
        </div>
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto max-w-6xl px-4 md:px-8 py-6 flex flex-col md:flex-row md:items-center gap-x-6 gap-y-1 text-base">
          <Link href="/privacy" className="inline-flex items-center min-h-11 font-medium text-foreground underline decoration-brand decoration-2 underline-offset-4">
            Privacy
          </Link>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="inline-flex items-center min-h-11 font-medium text-foreground underline decoration-brand decoration-2 underline-offset-4">
            View source on GitHub
          </a>
          <span className="md:ml-auto py-2 text-muted-foreground">MemeGPT. Built for fun, not for profit.</span>
        </div>
      </footer>
      <MobileNav fixed />
    </div>
  );
}

function Cover() {
  // The order is drawn after mount: the server can't know it, and drawing
  // it during render would disagree with the server's HTML.
  const [position, setPosition] = useState<number | null>(null);
  const reduceMotion = useReducedMotion();
  const slotRef = useRef<HTMLDivElement>(null);
  // The lead meme waits for the slot's first measurement, so it never
  // shows at a stand-in size and then jumps.
  const [measured, setMeasured] = useState(false);

  useEffect(() => {
    setPosition(leadPosition);
  }, []);

  // The slot's height comes from flex, which container units can't read
  // (Chrome resolves 100cqh to 0 inside a flexed size container), so the
  // meme's height limit is the slot's measured height, kept current here.
  useEffect(() => {
    const slot = slotRef.current;
    if (!slot) return;
    const observer = new ResizeObserver(([entry]) => {
      slot.style.setProperty("--slot-h", `${Math.floor(entry.contentRect.height)}px`);
      setMeasured(true);
    });
    observer.observe(slot);
    return () => observer.disconnect();
  }, []);

  const order = position === null ? null : visitOrder();
  const story = order && position !== null ? LEAD_STORIES[order[position % order.length]] : null;

  function nextStory() {
    if (!order || position === null) return;
    const next = (position + 1) % order.length;
    const target = LEAD_STORIES[order[next]];
    // Swap once the next image is ready, so the slot never shows a blank.
    const img = new Image();
    const go = () => {
      leadPosition = next;
      setPosition(next);
    };
    img.onload = go;
    img.onerror = go;
    img.src = target.image;
  }

  return (
    // One screen tall below the masthead (and above the phone's tab bar), so
    // the lead slot takes whatever the headline and composer leave and the
    // composer stays above the fold at any window height.
    <section
      aria-labelledby="landing-headline"
      className="mx-auto max-w-6xl px-4 md:px-8 pt-4 md:pt-8 pb-6 md:pb-8 flex flex-col
                 min-h-[calc(100svh-3.5rem-2px-3rem-1px-env(safe-area-inset-bottom))] md:min-h-[calc(100svh-74px)]"
    >
      <h1
        id="landing-headline"
        className="font-display text-[length:var(--text-display)] leading-[0.95] text-foreground text-balance"
      >
        {HEADLINE}
      </h1>
      <p className="mt-3 md:mt-4 max-w-2xl text-lg md:text-xl text-foreground">{SUBLINE}</p>

      <article aria-label="Lead story" className="mt-4 md:mt-6 flex-1 flex flex-col min-h-0">
        <div className="flex items-start justify-between gap-4 min-h-11">
          <p className="py-2.5 text-base font-medium text-foreground" aria-live="polite">
            {story?.prompt}
          </p>
          <button
            type="button"
            onClick={nextStory}
            disabled={!story}
            className="shrink-0 min-h-11 text-base font-medium text-foreground underline decoration-brand
                       decoration-2 underline-offset-4 hover:decoration-[3px] disabled:opacity-40"
          >
            {NEXT_STORY}
          </button>
        </div>
        {/* The slot's height is set by the space left, between 12rem and
            30rem; the meme fits inside its measured height. */}
        <div ref={slotRef} className="relative flex-1 min-h-48 max-h-[30rem]">
          {/* Nothing is inside on the first render, so the first story fades
              in the same way Next story's do. */}
          <AnimatePresence initial={false}>
            {story && measured && (
              <motion.div
                key={story.image}
                initial={reduceMotion ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={reduceMotion ? INSTANT : SETTLE}
                className="absolute inset-0 flex items-center justify-center"
              >
                <MemeDisplay
                  url={story.image}
                  alt={`A meme MemeGPT made for: ${story.prompt}`}
                  className="flex justify-center max-w-full max-h-full"
                  maxHeightClassName="max-h-[calc(var(--slot-h)-1rem-4px)] md:max-h-[calc(var(--slot-h)-1.5rem-4px)]"
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </article>

      <div className="mt-4 md:mt-6">
        <Composer />
      </div>
    </section>
  );
}

interface PickedPhoto {
  file: File;
  previewUrl: string;
}

/**
 * The landing composer. Make a meme opens Chat with this as the first
 * message; with nothing typed or picked it simply opens Chat. Photos are
 * checked by the same limits as Chat's.
 */
function Composer() {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const fieldId = useId();
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [pickError, setPickError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const photosRef = useRef<PickedPhoto[]>([]);

  useEffect(() => {
    photosRef.current = photos;
  }, [photos]);

  useEffect(() => {
    return () => photosRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
  }, []);

  async function handleFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;
    if (files.some((f) => f.size > MAX_IMAGE_BYTES)) {
      setPickError(PICK_TOO_LARGE);
      return;
    }
    if (photos.length + files.length > MAX_IMAGES_PER_MESSAGE) {
      setPickError(PICK_TOO_MANY);
      return;
    }
    if (!(await allSupportedImages(files))) {
      setPickError(PICK_UNSUPPORTED);
      return;
    }
    setPhotos((prev) => [...prev, ...files.map((file) => ({ file, previewUrl: URL.createObjectURL(file) }))]);
    setPickError(null);
  }

  function remove(index: number) {
    setPhotos((prev) => {
      const target = prev[index];
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
    setPickError(null);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const message = text.trim();
    if (message || photos.length > 0) {
      handToChat({ text: message, files: photos.map((p) => p.file) });
    }
    router.push("/chat");
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 max-w-3xl">
      <ul aria-label="Attached photos" className="flex flex-wrap gap-x-3 gap-y-1 empty:hidden">
        <AnimatePresence initial={false}>
          {photos.map((p, i) => (
            <motion.li
              key={p.previewUrl}
              initial={reduceMotion ? false : { opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={reduceMotion ? INSTANT : FAST_SETTLE}
              className="flex items-center gap-1"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- local preview */}
              <img src={p.previewUrl} alt={`Attached photo ${i + 1}`} className="w-12 h-12 object-cover border border-border" />
              <button
                type="button"
                onClick={() => remove(i)}
                aria-label={`Remove photo ${i + 1}`}
                className="min-h-11 px-2 text-base text-muted-foreground hover:text-foreground underline underline-offset-4
                           transition-colors duration-[var(--duration-fast)]"
              >
                Remove
              </button>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
      <div className="flex flex-col md:flex-row gap-2">
        <label htmlFor={fieldId} className="sr-only">
          Message
        </label>
        <input
          id={fieldId}
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          enterKeyHint="send"
          placeholder={photos.length > 0 ? "Add a caption (optional)" : "What happened?"}
          className="w-full md:flex-1 min-h-12 px-3 text-base bg-background border border-input rounded-sm
                     placeholder:text-muted-foreground"
        />
        <div className="flex gap-2">
          <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFiles} className="hidden" />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="min-h-12 px-5 border border-input rounded-sm text-base font-medium text-foreground
                       hover:bg-muted transition-colors duration-[var(--duration-fast)]"
          >
            Photo
          </button>
          <button
            type="submit"
            className="flex-1 md:flex-none min-h-12 px-6 rounded-sm bg-primary text-primary-foreground
                       text-base font-semibold hover:bg-primary/85 transition-colors duration-[var(--duration-fast)]"
          >
            Make a meme
          </button>
        </div>
      </div>
      {pickError && (
        <p role="alert" className="text-base text-foreground border-l-2 border-brand pl-3">
          {pickError}
        </p>
      )}
    </form>
  );
}

/** One mode's story: its words on the left from 1024px up, its meme beside them. */
function Story({
  id,
  kicker,
  title,
  body,
  link,
  href,
  children,
}: {
  id: string;
  kicker: string;
  title: string;
  body: string;
  link: string;
  href: string;
  children: React.ReactNode;
}) {
  return (
    <article aria-labelledby={id} className="py-10 md:py-14 border-t-2 border-foreground">
      <div className="lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12 lg:items-start">
        <div>
          <p className="text-sm font-bold uppercase tracking-wide text-brand">{kicker}</p>
          <h2 id={id} className="mt-2 font-display text-[length:var(--text-title)] leading-[0.95] text-foreground">
            {title}
          </h2>
          <p className="mt-3 text-lg text-foreground max-w-prose">{body}</p>
          <Link href={href} className={`mt-3 ${STORY_LINK}`}>
            {link}
          </Link>
        </div>
        <div className="mt-6 lg:mt-0 min-w-0">{children}</div>
      </div>
    </article>
  );
}

function ChatStory() {
  const prompt = "day 1 of the gym vs day 2";
  return (
    <Story
      id="story-chat"
      kicker="Chat"
      title="Talk to MemeGPT like any chatbot."
      body="Type a thought, attach a photo if you want, and get a meme back. MemeGPT never breaks character. Every reply comes back as a meme."
      link="Open Chat"
      href="/chat"
    >
      <p className="text-lg md:text-xl font-semibold leading-snug text-foreground">{prompt}</p>
      <MemeDisplay
        url="/landing/loop_9.png"
        alt={`A meme MemeGPT made for: ${prompt}`}
        className="mt-3 flex justify-start"
        maxHeightClassName={STORY_IMAGE_HEIGHT}
      />
    </Story>
  );
}

function LoreStory() {
  const [expanded, setExpanded] = useState(false);
  const transcriptId = useId();
  const shown = expanded ? SHARED_CHAT : SHARED_CHAT.slice(0, 2);
  return (
    <Story
      id="story-lore"
      kicker="Lore"
      title="Drop in the whole story."
      body="Paste a whole group chat or upload a stack of screenshots. Get back several memes, one for every moment worth remembering."
      link="Open Lore"
      href="/lore"
    >
      <div className="border-l-2 border-border pl-3">
        <ol id={transcriptId} aria-label="The group chat" className="flex flex-col gap-0.5 text-base text-foreground">
          {shown.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
        {!expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            aria-controls={transcriptId}
            aria-expanded={expanded}
            className="min-h-11 text-base font-medium text-foreground underline decoration-brand decoration-2 underline-offset-4"
          >
            more messages
          </button>
        )}
      </div>
      <ol className="mt-6 flex flex-col gap-8">
        {LORE_EXAMPLES.map((example) => (
          <li key={example.image} className="md:grid md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] md:gap-6">
            <blockquote className="text-base text-foreground">
              {example.lines.map((n) => (
                <p key={n}>{SHARED_CHAT[n - 1]}</p>
              ))}
            </blockquote>
            <MemeDisplay
              url={example.image}
              alt={`A meme MemeGPT made from: ${example.lines.map((n) => SHARED_CHAT[n - 1]).join(" ")}`}
              className="mt-2 md:mt-0 flex justify-start"
              maxHeightClassName="max-h-[50vh] md:max-h-[22rem]"
            />
          </li>
        ))}
      </ol>
    </Story>
  );
}

function MakeStory() {
  return (
    <Story
      id="story-make"
      kicker="Make"
      title="Pick the template yourself."
      body="Skip the AI's judgment entirely. Search the full template library, write your own captions box by box, and render it exactly your way."
      link="Open Make"
      href="/make"
    >
      <dl className="text-base text-foreground">
        <dt className="text-sm font-bold uppercase tracking-wide text-muted-foreground">Drake</dt>
        <dd className="mt-1 flex gap-2">
          <span aria-hidden className="font-bold">1</span>
          <span className="sr-only">Box 1:</span>letting the AI pick
        </dd>
        <dd className="flex gap-2">
          <span aria-hidden className="font-bold">2</span>
          <span className="sr-only">Box 2:</span>picking it yourself
        </dd>
      </dl>
      <MemeDisplay
        url="/landing/make_example.png"
        alt="Drake meme: rejecting letting the AI pick, approving picking it yourself"
        className="mt-3 flex justify-start"
        maxHeightClassName={STORY_IMAGE_HEIGHT}
      />
    </Story>
  );
}

function ArcStory() {
  return (
    <Story
      id="story-arc"
      kicker="Arc"
      title="See your meme era."
      body="Your most-summoned template, your longest streak, an aura score that goes up whether you like it or not. Roast copy included, free of charge."
      link="Open Arc"
      href="/arc"
    >
      <p className="text-sm font-bold uppercase tracking-wide text-muted-foreground">Example</p>
      <MemeDisplay
        url="/landing/arc_example.png"
        alt="An example Arc share card: 8,230 aura farmed, main character (unwell), 47 memes, 14 different templates"
        className="mt-2 flex justify-start"
        maxHeightClassName={STORY_IMAGE_HEIGHT}
      />
    </Story>
  );
}

function InBrief() {
  return (
    <section aria-labelledby="in-brief" className="py-10 md:py-14 border-t-2 border-foreground">
      <h2 id="in-brief" className="font-display text-[length:var(--text-title)] leading-[0.95] text-foreground">
        In brief
      </h2>
      <div className="mt-6 lg:grid lg:grid-cols-2 lg:gap-12">
        <div>
          <ul className="flex flex-col divide-y divide-border border-y border-border text-base text-foreground">
            {FACTS.map((fact) => (
              <li key={fact} className="py-2.5">
                {fact}
              </li>
            ))}
            <li className="py-0.5">
              <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className={STORY_LINK}>
                Open source on GitHub.
              </a>
            </li>
          </ul>
          <Link href="/privacy" className={`mt-3 ${STORY_LINK}`}>
            Privacy
          </Link>
        </div>
        <div className="mt-10 lg:mt-0">
          <h3 className={STORY_KICKER}>Questions, answered</h3>
          <ul className="flex flex-col">
            {FAQS.map((item) => (
              <Faq key={item.q} q={item.q} a={item.a} />
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function Faq({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  const answerId = useId();
  const reduceMotion = useReducedMotion();
  return (
    <li className="border-b border-border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={answerId}
        className="w-full min-h-11 py-2.5 flex items-start justify-between gap-4 text-left text-base font-semibold text-foreground"
      >
        {q}
        <span aria-hidden className="shrink-0 font-normal">
          {open ? "−" : "+"}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={answerId}
            initial={reduceMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={reduceMotion ? INSTANT : FAST_OUT}
            className="overflow-hidden"
          >
            <p className="pb-3 text-base text-foreground max-w-prose">{a}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}
