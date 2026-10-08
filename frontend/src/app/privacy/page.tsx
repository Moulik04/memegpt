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
          data team. This page says exactly what happens to what you send,
          in plain language, because that&apos;s more useful than a legal
          document nobody reads.
        </p>

        <Section title="Without signing in">
          <p>
            The first time you use MemeGPT, your browser makes up a random
            id and saves it on your device. That id is sent with your
            requests so MemeGPT can recognize the same browser next time.
            On its own it isn&apos;t tied to your name or your email.
          </p>
          <p>
            Kept against that id: a record of each meme you make (which
            template, when, and whether it came from Chat, Lore or Make),
            the meme image itself, and your 👍/👎 ratings. That record is
            what Arc counts. It is also how MemeGPT avoids repeating
            templates and leans toward the ones you like.
          </p>
          <p>
            The words you type are not saved. They are sent to the AI model
            that picks a template and writes the captions (in Make, it only
            checks that your captions are safe), and that is the end of
            them. The captions live on only as part of the meme image.
          </p>
        </Section>

        <Section title="Your memes">
          <p>
            Every meme MemeGPT makes is saved as an image so it can be
            shown and shared. Each one gets a link with a random address
            that can&apos;t be guessed. Anyone you give that link to can see
            the meme, without signing in. MemeGPT never lists or publishes
            your memes anywhere, and they stay until you delete them.
          </p>
        </Section>

        <Section title="Photos and screenshots">
          <p>
            Every image goes through the same safety steps before anything
            else touches it: size and type checks, all metadata (like your
            phone&apos;s GPS tags) removed by rebuilding the image from its
            pixels, and a content-safety check. For that check, and to
            understand what&apos;s in the picture, the image is sent to Groq,
            the same service that runs the AI model.
          </p>
          <p>
            Your original file is not kept. MemeGPT holds it only while
            your request is being handled and drops it when your memes are
            done or the request fails.
          </p>
          <p>
            If the safety check turns a photo down, MemeGPT counts that it
            happened and under which broad category (violence, for
            example). Nothing about the photo, its file name or who sent it
            is kept with that count.
          </p>
          <p>
            There is one exception, and you choose it: if you ask MemeGPT
            to &quot;make this a meme&quot;, your own photo becomes the meme. The
            captioned copy, with its metadata removed, is saved like any
            other meme.
          </p>
          <p>
            A photo sent from your phone&apos;s share sheet waits on the server
            for about 10 minutes so MemeGPT can pick it up when the app
            opens. If you never open it, the photo is dropped.
          </p>
        </Section>

        <Section title="Lore's 'remember lore' toggle">
          <p>
            Off by default. When you turn it on, MemeGPT pulls short
            recurring names and running jokes out of what you paste, never
            the whole text, so later memes can make callbacks. Turning it
            off again only stops new ones being added. What is already
            remembered stays until you erase it.
          </p>
        </Section>

        <Section title="If you sign in">
          <p>
            Sign-in is through Google, handled for MemeGPT by Supabase.
            Your Google name, email address and profile picture are stored
            with your account. MemeGPT never sees your password.
          </p>
          <p>
            Signing in turns on saved history, and saved history does store
            text. In Chat, MemeGPT saves your messages as you typed them,
            together with the memes they produced, so a conversation can be
            shown again on any device. In Lore, what is saved is a short
            summary of each moment MemeGPT found in your paste. When the
            paste is short, or MemeGPT can&apos;t split it into moments, the
            paste itself is saved. For a photo, the saved text is
            MemeGPT&apos;s description of the photo, not the photo. If you
            asked for your own photo to be captioned, your request and the
            captions are saved.
          </p>
          <p>
            Signing in also links the history already on that browser to
            your account.
          </p>
          <p>
            Every saved chat has its own delete button. Deleting a chat
            removes its messages, the memes it produced and their images,
            the ratings on those memes, and any lore picked up from it.
            Share links to those memes stop working.
          </p>
        </Section>

        <Section title="What MemeGPT doesn't keep">
          <p>
            Signed out, the text you send is not saved, and neither are
            your original photos. The one exception is remembered lore,
            and only if you turn it on. Signed in, your text is also saved
            as chat history, as described above. There&apos;s no ad tracking
            and no cross-site tracking pixel on this app.
          </p>
        </Section>

        <Section title="Daily limits">
          <p>
            MemeGPT runs on a free daily AI budget, so each browser and each
            network can make a limited number of memes a day. To count them,
            the server keeps your browser&apos;s id and your network address
            (your IP address) in its memory next to a number, for up to 24
            hours. That count is never written to the database, and it is
            gone whenever the server restarts.
          </p>
          <p>
            Separately, the companies that host MemeGPT see your network
            address, as the host of any website does, and keep their own
            access logs.
          </p>
        </Section>

        <Section title="Analytics">
          <p>
            MemeGPT uses Google Analytics to see aggregate things like which
            pages get visited and roughly how much traffic the app gets,
            not what you typed, uploaded, or generated. It&apos;s not linked
            to any ad network, and it&apos;s separate from the anonymous id
            described above.
          </p>
        </Section>

        <Section title="Who else touches this">
          <p>
            MemeGPT runs on other companies&apos; services. Each one gets only
            what its job needs.
          </p>
          <ul className="list-disc pl-5 space-y-1.5">
            <li>Vercel serves the website and passes your Chat and Lore messages on to the backend.</li>
            <li>Render runs the backend that makes the memes.</li>
            <li>Groq runs the AI model. It receives your messages, and your photos when you upload them.</li>
            <li>
              Google&apos;s Gemini turns your message into a search of the
              template library, so it receives your message text too. For a
              photo, it receives MemeGPT&apos;s description of the photo, not
              the photo. MemeGPT uses Gemini&apos;s free tier. Under
              Google&apos;s terms for that tier, Google may use what it
              receives to improve its products, and people at Google may read
              it. Please don&apos;t put anything in a message that you
              wouldn&apos;t want a stranger to read.
            </li>
            <li>Cloudflare stores the finished meme images.</li>
            <li>Supabase runs sign-in and hosts the database that holds everything described on this page.</li>
            <li>Google provides the sign-in button and Analytics.</li>
          </ul>
          <p>MemeGPT doesn&apos;t sell your data.</p>
        </Section>

        <Section title="Forget me">
          <p>
            The &quot;Forget me&quot; link in the header erases what MemeGPT
            holds about you and clears the id from your device.
          </p>
          <p>
            Signed in, that means everything on your account: saved chats
            and their messages, your memes and their images, your ratings,
            and any remembered lore. It also covers anything from this
            browser that isn&apos;t part of an account. Signed out, it means
            everything tied to this browser&apos;s id that isn&apos;t part of an
            account. History that belongs to an account can only be erased
            while you are signed in to it, because a browser id on its own
            doesn&apos;t prove who is asking.
          </p>
          <p>
            Deleted memes are really deleted, so share links to them stop
            working. If MemeGPT can&apos;t finish the erase, it says so
            instead of pretending it worked, and you can try again.
          </p>
          <p>
            Forget me doesn&apos;t delete the sign-in account itself. If you
            want that gone too, email{" "}
            <a
              href="mailto:support.memegpt@gmail.com"
              className="underline hover:text-gray-200 transition-colors"
            >
              support.memegpt@gmail.com
            </a>{" "}
            and it will be deleted by hand.
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
