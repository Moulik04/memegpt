"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Plus } from "lucide-react";
import { ApiError, generateMeme, listTemplates, memeImageUrl } from "@/lib/api";
import { GENERAL_FAILURE } from "@/lib/notices";
import BudgetNotice from "./BudgetNotice";
import { MemeDisplay } from "./MemeDisplay";
import { MEME_ACTION, MemeActions } from "./MemeActions";
import type { ExplainResponse, TextBoxInfo } from "@/types";

/** Copy deck, section 7.4. */
const SEARCH_PLACEHOLDER = "Search templates by name, vibe or tag";
const NO_MATCHES = "No templates found. Try another search.";
const CAPTION_REFUSED = "That caption couldn't be used. Try different text.";
const RENDER_FAILED = "That didn't render. Your captions are still here. Try again.";

/** Fisher-Yates. GET /explain/ always lists templates in the same order, so
 * without a shuffle the same few would always come first and get picked. */
function shuffle<T>(arr: T[]): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

// The shuffled library, kept for the visit (until the page reloads), so
// Change template, Make another and a trip to another tab all come back to
// the same list.
let visitOrder: ExplainResponse[] | null = null;

const fullUrl = (url: string) => (url.startsWith("http") ? url : memeImageUrl(url));
const isGif = (t: ExplainResponse) => !!t.image_url && /\.gif(?:$|\?)/i.test(t.image_url);
const hasText = (captions: Record<string, string>) => Object.values(captions).some((v) => v.trim());

type Screen = "library" | "caption" | "finished";

/** What a failed render shows. The captions always stay. */
interface RenderNotice {
  text: string;
  budget: boolean;
}

function renderNotice(err: unknown): RenderNotice {
  if (err instanceof ApiError) {
    // A notice the backend named (busy, the daily budget, a limit) is
    // already in the deck's wording.
    if (err.reason) return { text: err.message, budget: err.reason === "site_budget" };
    // The captions are checked together, so the refusal can't say which.
    if (err.status === 400) return { text: CAPTION_REFUSED, budget: false };
  }
  return { text: RENDER_FAILED, budget: false };
}

/**
 * Make: no AI judgment. Pick a template from the library, write the
 * captions box by box on a numbered template, render.
 */
export function MakeView() {
  const [templates, setTemplates] = useState<ExplainResponse[] | null>(visitOrder);
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState("");
  const [screen, setScreen] = useState<Screen>("library");
  const [selected, setSelected] = useState<ExplainResponse | null>(null);
  // By template id, so going back and picking the same template again keeps
  // what was typed.
  const [captionsByTemplate, setCaptionsByTemplate] = useState<Record<string, Record<string, string>>>({});
  const [rendering, setRendering] = useState(false);
  const [notice, setNotice] = useState<RenderNotice | null>(null);
  const [result, setResult] = useState<{ url: string; memeId?: string } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const listingRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (visitOrder) return;
    let cancelled = false;
    setLoadFailed(false);
    listTemplates()
      .then((data) => {
        if (cancelled) return;
        visitOrder = shuffle(data);
        setTemplates(visitOrder);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // Focus follows the screen: the template's name on the caption and
  // finished screens, the last template's listing back in the library.
  useEffect(() => {
    if (screen === "library") {
      const listing = selected ? listingRefs.current[selected.template_id] : null;
      if (listing) {
        listing.scrollIntoView({ block: "center" });
        listing.focus({ preventScroll: true });
      }
      return;
    }
    scrollRef.current?.scrollTo({ top: 0 });
    headingRef.current?.focus();
    // Only a screen change moves focus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen]);

  const filtered = useMemo(() => {
    if (!templates) return [];
    const q = search.trim().toLowerCase();
    if (!q) return templates;
    return templates.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) ||
        t.tags.some((tag) => tag.toLowerCase().includes(q)),
    );
  }, [templates, search]);

  const captions = selected ? (captionsByTemplate[selected.template_id] ?? {}) : {};

  function choose(t: ExplainResponse) {
    setSelected(t);
    setNotice(null);
    setResult(null);
    setScreen("caption");
  }

  function backToLibrary() {
    setNotice(null);
    setResult(null);
    setScreen("library");
  }

  function setCaption(label: string, value: string) {
    if (!selected) return;
    const id = selected.template_id;
    setCaptionsByTemplate((prev) => ({ ...prev, [id]: { ...prev[id], [label]: value } }));
  }

  async function render(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || rendering || !hasText(captions)) return;
    setRendering(true);
    setNotice(null);
    try {
      const texts = Object.fromEntries(selected.text_boxes.map((b) => [b.label, captions[b.label] ?? ""]));
      const res = await generateMeme({ template_id: selected.template_id, texts });
      setResult({ url: res.meme_url, memeId: res.meme_id });
      // A finished meme starts the next one fresh.
      setCaptionsByTemplate((prev) => ({ ...prev, [selected.template_id]: {} }));
      setScreen("finished");
    } catch (err) {
      setNotice(renderNotice(err));
    } finally {
      setRendering(false);
    }
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto chat-scroll">
      <div className="mx-auto max-w-6xl px-4 md:px-8 pt-6 md:pt-8 pb-12">
        <h1 className="sr-only">Make</h1>

        {screen === "library" && (
          <Library
            templates={templates}
            filtered={filtered}
            loadFailed={loadFailed}
            onRetry={() => setAttempt((n) => n + 1)}
            search={search}
            onSearch={setSearch}
            searchRef={searchRef}
            selectedId={selected?.template_id ?? null}
            listingRefs={listingRefs}
            onChoose={choose}
          />
        )}

        {screen === "caption" && selected && (
          <form onSubmit={render} className="flex flex-col gap-6">
            <ChangeTemplate onClick={backToLibrary} />
            <h2
              ref={headingRef}
              tabIndex={-1}
              className="font-display text-3xl md:text-5xl leading-none text-foreground focus:outline-none"
            >
              {selected.name}
            </h2>
            {/* The fields sit right beside the template, however narrow it is. */}
            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-12">
              <NumberedTemplate template={selected} />
              <div className="flex flex-col gap-4 lg:w-96 lg:shrink-0">
                <ol className="flex flex-col gap-3">
                  {selected.text_boxes.map((box, i) => (
                    <li key={box.label} className="flex items-center gap-3">
                      <Marker n={i + 1} />
                      <input
                        type="text"
                        value={captions[box.label] ?? ""}
                        onChange={(e) => setCaption(box.label, e.target.value)}
                        aria-label={`Caption ${i + 1}`}
                        placeholder={String(i + 1)}
                        disabled={rendering}
                        className="flex-1 min-w-0 min-h-12 px-3 text-base bg-background border border-input rounded-sm
                                   placeholder:text-muted-foreground disabled:opacity-60"
                      />
                    </li>
                  ))}
                </ol>
                <div className="flex flex-wrap items-center gap-4">
                  <button
                    type="submit"
                    disabled={rendering || !hasText(captions)}
                    aria-busy={rendering}
                    className="w-full sm:w-auto min-h-12 px-8 rounded-sm bg-primary text-primary-foreground text-base
                               font-semibold hover:bg-primary/85 disabled:opacity-40
                               transition-colors duration-[var(--duration-fast)]"
                  >
                    Render
                  </button>
                  <p role="status" className="text-base text-foreground">
                    {rendering ? "Rendering…" : ""}
                  </p>
                </div>
                {notice &&
                  (notice.budget ? (
                    <BudgetNotice message={notice.text} maxHeightClassName="max-h-[40vh]" />
                  ) : (
                    <p role="alert" className="text-base text-foreground border-l-2 border-brand pl-3 max-w-prose">
                      {notice.text}
                    </p>
                  ))}
              </div>
            </div>
          </form>
        )}

        {screen === "finished" && selected && result && (
          <div className="flex flex-col gap-4">
            <h2 ref={headingRef} tabIndex={-1} className="sr-only">
              {selected.name}
            </h2>
            <div className="w-full lg:w-fit max-w-full">
              <MemeDisplay
                url={result.url}
                alt={selected.name}
                className="flex justify-start"
                maxHeightClassName="max-h-[60vh] lg:max-h-[min(72vh,760px)]"
              />
              <div className="mt-1">
                <MemeActions
                  url={result.url}
                  memeId={result.memeId}
                  lead={
                    <button type="button" onClick={backToLibrary} className={MEME_ACTION}>
                      <Plus size={16} strokeWidth={2} aria-hidden="true" />
                      Make another
                    </button>
                  }
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ChangeTemplate({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="self-start -ml-1 min-h-11 px-1 inline-flex items-center gap-1.5 text-base font-medium text-foreground
                 underline decoration-brand decoration-2 underline-offset-4 hover:decoration-[3px]"
    >
      <ArrowLeft size={16} strokeWidth={2} aria-hidden="true" />
      Change template
    </button>
  );
}

function Marker({ n, className = "", style }: { n: number; className?: string; style?: React.CSSProperties }) {
  return (
    <span
      aria-hidden="true"
      style={style}
      className={`inline-flex shrink-0 items-center justify-center h-7 min-w-7 px-1 bg-foreground text-background
                  text-sm font-bold leading-none ${className}`}
    >
      {n}
    </span>
  );
}

/**
 * An animated template's first frame, drawn once to a canvas so nothing in
 * the library or the caption screen moves. Sized like an <img>: the
 * caller's classes decide how far it scales down.
 */
function StillImage({ src, alt, className }: { src: string; alt: string; className: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      canvas.getContext("2d")?.drawImage(img, 0, 0);
    };
    img.src = src;
  }, [src]);
  return <canvas ref={canvasRef} role="img" aria-label={alt} className={className} />;
}

function TemplateImage({ template, className }: { template: ExplainResponse; className: string }) {
  if (!template.image_url) return null;
  const src = fullUrl(template.image_url);
  return isGif(template) ? (
    <StillImage src={src} alt={template.name} className={className} />
  ) : (
    // eslint-disable-next-line @next/next/no-img-element -- natural size, any origin
    <img src={src} alt={template.name} loading="lazy" className={className} />
  );
}

/** The bare template with a numbered marker at the top left of each
 * caption box, placed from the same positions the compositor draws at. */
function NumberedTemplate({ template }: { template: ExplainResponse }) {
  const placed = template.text_boxes.every((b: TextBoxInfo) => b.x_pct !== undefined && b.y_pct !== undefined);
  return (
    <figure className="w-fit max-w-full min-w-0 bg-meme-mat border border-meme-edge p-2 md:p-3">
      <div className="relative">
        <TemplateImage
          template={template}
          className="block w-auto h-auto max-w-full max-h-[55vh] lg:max-h-[min(70vh,720px)] border border-meme-edge"
        />
        {placed &&
          template.text_boxes.map((box, i) => (
            <Marker
              key={box.label}
              n={i + 1}
              className="absolute outline outline-2 outline-background"
              // A box can start at the very edge; the marker stays inside.
              style={{
                left: `min(${box.x_pct}%, calc(100% - 1.75rem))`,
                top: `min(${box.y_pct}%, calc(100% - 1.75rem))`,
              }}
            />
          ))}
      </div>
    </figure>
  );
}

interface LibraryProps {
  templates: ExplainResponse[] | null;
  filtered: ExplainResponse[];
  loadFailed: boolean;
  onRetry: () => void;
  search: string;
  onSearch: (value: string) => void;
  searchRef: React.RefObject<HTMLInputElement>;
  selectedId: string | null;
  listingRefs: React.MutableRefObject<Record<string, HTMLButtonElement | null>>;
  onChoose: (t: ExplainResponse) => void;
}

function Library({
  templates,
  filtered,
  loadFailed,
  onRetry,
  search,
  onSearch,
  searchRef,
  selectedId,
  listingRefs,
  onChoose,
}: LibraryProps) {
  return (
    <div className="max-w-3xl">
      <div role="search" className="flex flex-col sm:flex-row gap-2">
        <input
          ref={searchRef}
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onSearch("");
          }}
          aria-label="Search templates"
          placeholder={SEARCH_PLACEHOLDER}
          // "Clear search" does what the browser's own clear button would.
          className="w-full sm:flex-1 min-h-12 px-3 text-base bg-background border border-input rounded-sm
                     placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:appearance-none"
        />
        {search && (
          <button
            type="button"
            onClick={() => {
              onSearch("");
              searchRef.current?.focus();
            }}
            className="self-start min-h-12 sm:px-4 text-base font-medium text-foreground underline decoration-brand
                       decoration-2 underline-offset-4"
          >
            Clear search
          </button>
        )}
      </div>

      {loadFailed && (
        <div role="alert" className="mt-6 border-l-2 border-brand pl-3">
          <p className="text-base font-semibold text-foreground">{GENERAL_FAILURE.heading}</p>
          <p className="text-base text-foreground">{GENERAL_FAILURE.text}</p>
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 text-base font-medium text-foreground underline decoration-brand decoration-2
                       underline-offset-4"
          >
            Try again
          </button>
        </div>
      )}

      {!templates && !loadFailed && (
        <ul aria-busy="true" aria-label="Templates" className="mt-4">
          {Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="py-3 border-b border-border">
              <div className="h-24 w-24 md:h-32 md:w-32 bg-meme-mat border border-meme-edge" />
            </li>
          ))}
        </ul>
      )}

      {templates && filtered.length === 0 && (
        <p role="status" className="mt-6 text-base text-foreground">
          {NO_MATCHES}
        </p>
      )}

      {templates && filtered.length > 0 && (
        <ul aria-label="Templates" className="mt-4">
          {filtered.map((t) => {
            const chosen = t.template_id === selectedId;
            return (
              <li key={t.template_id} className="border-b border-border">
                <button
                  ref={(el) => {
                    listingRefs.current[t.template_id] = el;
                  }}
                  type="button"
                  onClick={() => onChoose(t)}
                  aria-current={chosen ? "true" : undefined}
                  aria-label={`Choose template: ${t.name}${isGif(t) ? " (GIF)" : ""}`}
                  className={`group w-full grid grid-cols-[6rem_minmax(0,1fr)] md:grid-cols-[8rem_minmax(0,1fr)] gap-4
                              items-center py-3 text-left hover:bg-muted transition-colors
                              duration-[var(--duration-fast)] ${chosen ? "border-l-2 border-brand pl-3" : ""}`}
                >
                  <span className="flex items-center justify-center h-24 w-24 md:h-32 md:w-32 bg-meme-mat border border-meme-edge p-1">
                    <TemplateImage template={t} className="block max-h-full max-w-full w-auto h-auto" />
                  </span>
                  <span className="flex flex-col gap-1 min-w-0">
                    <span className="flex items-center gap-2">
                      <span className="text-lg font-semibold leading-snug text-foreground">{t.name}</span>
                      {isGif(t) && (
                        <span className="shrink-0 border border-foreground px-1.5 text-xs font-bold leading-5 text-foreground">
                          GIF
                        </span>
                      )}
                    </span>
                    <span className="text-sm text-muted-foreground line-clamp-2">{t.description}</span>
                    <span className="text-base font-medium text-foreground underline decoration-brand decoration-2 underline-offset-4 self-start group-hover:decoration-[3px]">
                      Choose template
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
