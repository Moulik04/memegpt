"use client";

import { useEffect, useState } from "react";

/** How far down the window a section's top must pass to count as being read. */
const READING_LINE = 0.35;

/**
 * The privacy page's section links, one per line, each a 44px target. The
 * section being read is marked with a red rule and aria-current: the last
 * one whose top has passed the reading line, or the one just picked from
 * this list, since the last few sections are too short to reach the line.
 */
export function PrivacyNav({ sections }: { sections: readonly { id: string; title: string }[] }) {
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    let picked: string | null = null;
    let frame = 0;

    function update() {
      frame = 0;
      const line = window.innerHeight * READING_LINE;
      let reading: string | null = null;
      for (const s of sections) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= line) reading = s.id;
      }
      const atBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
      setCurrent(atBottom && picked ? picked : reading);
    }
    function onScroll() {
      if (!frame) frame = requestAnimationFrame(update);
    }
    function onHash() {
      const id = decodeURIComponent(window.location.hash.slice(1));
      picked = sections.some((s) => s.id === id) ? id : null;
      update();
    }

    onHash();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("hashchange", onHash);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [sections]);

  return (
    <nav aria-label="Sections" className="mt-6">
      <ol className="flex flex-col border-y border-border">
        {sections.map((s) => {
          const isCurrent = s.id === current;
          return (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                aria-current={isCurrent ? "location" : undefined}
                className={`flex items-center min-h-11 pl-3 text-base text-foreground border-l-4 transition-colors
                            duration-[var(--duration-fast)] hover:underline underline-offset-4 ${
                              isCurrent ? "border-brand font-semibold" : "border-transparent"
                            }`}
              >
                {s.title}
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
