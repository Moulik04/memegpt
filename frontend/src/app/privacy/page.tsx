import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What MemeGPT collects, what it doesn't, and how to erase it.",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-lg font-bold text-gray-100">{title}</h2>
      <div className="mt-3 text-sm text-gray-400 leading-relaxed space-y-3">{children}</div>
    </section>
  );
}

export default function PrivacyPage() {
  return (
    <div className="min-h-dvh px-6 py-12">
      <div className="max-w-2xl mx-auto">
        <Link href="/" className="caption caption-mark text-xl">
          MemeGPT
        </Link>

        <h1 className="mt-8 text-3xl font-bold tracking-tight">Privacy</h1>
        <p className="mt-3 text-sm text-gray-500 leading-relaxed">
          MemeGPT is a small, self-funded side project, not a company with a
          data team. This page says exactly what happens to what you send
          it, in plain language, because that's more useful than a legal
          document nobody reads.
        </p>

        <Section title="Without signing in">
          <p>
            The first time you use MemeGPT, your browser generates a random
            id and saves it on your device. It gets sent along with your
            requests so MemeGPT can recognize repeat visits — it's never
            tied to your name, email, or anything else identifying.
          </p>
          <p>
            Tied to that id: which templates MemeGPT has picked for you
            recently (so it's less repetitive), and a light preference
            signal from your 👍/👎 feedback. Neither is a hard rule, just a
            nudge.
          </p>
        </Section>

        <Section title="Photos and screenshots">
          <p>
            Every image goes through the same safety pipeline before
            anything touches it: size/type checks, all EXIF metadata (like
            your phone's GPS tags) stripped by rebuilding the image from raw
            pixels, and a content-safety check. The original file is never
            written to disk — it exists in memory only for the length of
            your request, and is discarded the moment your meme is
            generated or the request fails. Only the resulting meme (the
            same image you see on screen) is kept, exactly like every other
            meme MemeGPT generates.
          </p>
        </Section>

        <Section title="Lore's 'remember lore' toggle">
          <p>
            Off by default. When you turn it on, MemeGPT extracts short
            recurring names and running jokes from what you paste — never
            the raw text itself — so future memes can make callbacks.
            Turning it back off just stops new extraction; anything already
            remembered stays until you erase it.
          </p>
        </Section>

        <Section title="If you sign in">
          <p>
            Signing in (Google or email) is handled by Supabase — MemeGPT
            never sees or stores your password. Signing in adds one thing:
            your chat/lore history is saved and synced across devices,
            tied to your account instead of just a browser. Nothing about
            what you type or upload is different from being signed out.
          </p>
        </Section>

        <Section title="What's never stored">
          <p>
            The actual text you send and the actual captions MemeGPT
            writes are never saved to the database — only the rendered
            meme image itself is kept, the same way a template's usage
            count is kept. There's no ad tracking and no cross-site
            tracking pixel on this app.
          </p>
        </Section>

        <Section title="Analytics">
          <p>
            MemeGPT uses Google Analytics to see aggregate things like which
            pages get visited and roughly how much traffic the app gets —
            not what you typed, uploaded, or generated. It's not linked to
            any ad network, and it's separate from the anonymous id
            described above.
          </p>
        </Section>

        <Section title="Who else touches this">
          <p>
            MemeGPT runs on Vercel (frontend) and Render (backend), with
            Supabase for sign-in, Groq for the language model that reads
            your message and picks a template, and Google Analytics for
            traffic stats. Each only sees what it needs to do its one job —
            none of them are in the business of selling your data, and
            neither is MemeGPT.
          </p>
        </Section>

        <Section title="Forget me">
          <p>
            The &quot;Forget me&quot; link in the header (Chat and Lore)
            permanently deletes everything tied to your id — generated
            memes&apos; association with you, feedback history, and any
            saved lore — and clears the id from your device. The next
            request starts completely fresh.
          </p>
        </Section>

        <Section title="Kids">
          <p>
            MemeGPT isn&apos;t directed at children under 13, and knowingly
            doesn&apos;t collect data from them.
          </p>
        </Section>

        <Section title="Changes">
          <p>
            If what MemeGPT collects changes in a way that matters, this
            page changes first. No silent updates.
          </p>
        </Section>

        <p className="mt-12 text-xs text-gray-600">
          Questions?{" "}
          <a
            href="https://github.com/Moulik04/memegpt/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-gray-400 transition-colors"
          >
            Open an issue on GitHub
          </a>
          .
        </p>
      </div>
    </div>
  );
}
