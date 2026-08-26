"use client";

import { useEffect, useMemo, useState } from "react";
import { generateMeme, listTemplates, memeImageUrl } from "@/lib/api";
import { MemeCard } from "./MemeCard";
import type { ExplainResponse } from "@/types";

/** Fisher-Yates — GET /explain/ always returns templates in the same
 * fixed order (ChromaDB's insertion order), so without this the grid
 * looked identical on every visit. */
function shuffle<T>(arr: T[]): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

/**
 * Make — the manual meme-maker (Phase 4, surfaces POST /generate/ +
 * GET /explain/, both fully built on the backend with typed frontend API
 * helpers already written but never called from any UI before this).
 * Unlike Chat/Lore, no LLM is involved at all: pick a template, write
 * your own captions, done. Stateless — no conversation, no sidebar, same
 * tier as Arc.
 */
export function MakeView() {
  const [templates, setTemplates] = useState<ExplainResponse[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<ExplainResponse | null>(null);
  const [captions, setCaptions] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [result, setResult] = useState<{ url: string; templateId: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    listTemplates()
      .then((data) => {
        if (!cancelled) setTemplates(shuffle(data));
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Couldn't load templates.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  function pickTemplate(t: ExplainResponse) {
    setSelected(t);
    setResult(null);
    setGenError(null);
    setCaptions(Object.fromEntries(t.text_boxes.map((b) => [b.label, ""])));
  }

  function backToGrid() {
    setSelected(null);
    setResult(null);
    setGenError(null);
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    if (!selected || generating) return;
    setGenerating(true);
    setGenError(null);
    try {
      const res = await generateMeme({ template_id: selected.template_id, texts: captions });
      setResult({ url: res.meme_url, templateId: res.template_id });
    } catch (err) {
      setGenError(err instanceof Error ? err.message : "Couldn't generate that meme — try again.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 chat-scroll">
      <div className="max-w-4xl mx-auto">
        {!selected ? (
          <>
            <div className="mb-6">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search templates — name, vibe, tags…"
                className="w-full bg-card border border-border rounded-xl px-4 py-3
                           text-sm placeholder-gray-600 focus:outline-none
                           focus:ring-2 focus:ring-accent/50 focus:border-accent transition-all"
              />
            </div>

            {loadError && (
              <p className="text-destructive text-xs bg-destructive/10 border border-destructive/30
                            rounded-xl px-3 py-2 mb-4">
                {loadError}
              </p>
            )}

            {!templates && !loadError && (
              <p className="text-sm text-gray-500 text-center py-12">Loading templates…</p>
            )}

            {templates && filtered.length === 0 && (
              <p className="text-sm text-gray-500 text-center py-12">
                No templates match &ldquo;{search}&rdquo;.
              </p>
            )}

            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
              {filtered.map((t, i) => (
                <button
                  key={t.template_id}
                  onClick={() => pickTemplate(t)}
                  className="group arrive-settle rounded-xl overflow-hidden bg-card border border-border
                             hover:border-gray-700 hover:shadow-lg hover:-translate-y-0.5
                             transition-all duration-200 text-left"
                  style={{
                    animationDelay: `${Math.min(i, 24) * 20}ms`,
                    animationFillMode: "backwards",
                  }}
                >
                  <div className="aspect-square bg-ink-2 overflow-hidden">
                    {t.image_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={memeImageUrl(t.image_url)}
                        alt={t.name}
                        loading="lazy"
                        className="w-full h-full object-cover"
                      />
                    )}
                  </div>
                  <p className="px-2 py-1.5 text-[11px] text-gray-400 truncate group-hover:text-gray-200">
                    {t.name}
                  </p>
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="max-w-md mx-auto">
            <button
              onClick={backToGrid}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors mb-4"
            >
              ← Choose a different template
            </button>

            {!result ? (
              <form
                onSubmit={handleGenerate}
                className="rounded-2xl bg-card border border-border p-4 flex flex-col gap-3 shadow-lg"
              >
                <div className="flex items-center gap-3">
                  {selected.image_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={memeImageUrl(selected.image_url)}
                      alt={selected.name}
                      className="w-16 h-16 rounded-lg object-cover border border-border shrink-0"
                    />
                  )}
                  <div className="min-w-0">
                    <p className="text-sm font-semibold truncate">{selected.name}</p>
                    {selected.description && (
                      <p className="text-xs text-gray-500 truncate">{selected.description}</p>
                    )}
                  </div>
                </div>

                {selected.text_boxes.map((box) => (
                  <div key={box.label}>
                    <label className="block text-[11px] uppercase tracking-wide text-gray-500 mb-1">
                      {box.label.replace(/_/g, " ")}
                    </label>
                    <input
                      type="text"
                      value={captions[box.label] ?? ""}
                      onChange={(e) => setCaptions((prev) => ({ ...prev, [box.label]: e.target.value }))}
                      placeholder={box.description || undefined}
                      className="w-full bg-ink-2 border border-border rounded-lg px-3 py-2
                                 text-sm placeholder-gray-600 focus:outline-none
                                 focus:ring-2 focus:ring-accent/50 focus:border-accent transition-all"
                    />
                  </div>
                ))}

                {genError && <p className="text-destructive text-xs">{genError}</p>}

                <button
                  type="submit"
                  disabled={generating}
                  className="bg-accent hover:bg-accent/90 disabled:opacity-40 transition-colors
                             text-white text-sm font-semibold rounded-xl px-4 py-2.5"
                >
                  {generating ? "Rendering…" : "Generate meme"}
                </button>
              </form>
            ) : (
              <div className="arrive-settle">
                <MemeCard url={result.url} alt={selected.name} templateId={result.templateId} />
                <button
                  onClick={backToGrid}
                  className="mt-4 w-full text-center text-xs text-gray-500 hover:text-gray-300
                             transition-colors"
                >
                  Make another
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
