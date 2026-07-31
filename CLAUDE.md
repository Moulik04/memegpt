# MemeGPT — System Documentation

## Overview

MemeGPT is a chatbot that communicates exclusively through memes. `/` is a public marketing landing page, not the app itself — it explains the product and links into the two actual app surfaces: **Chat** (`/chat`) — a normal chatbot, the catch is it only replies in memes — and **Lore** (`/lore`) — for big context dumps: paste a whole group-chat thread, upload a stack of screenshots, get several memes back, with explicit controls (meme count, drag-and-drop) that Chat deliberately doesn't expose. "Lore" is a purely public-facing/UI name; internally everything still runs through the same segmentation → batch → SSE machinery described below, and the master-prompt-era "Phase 1/Phase 2" language for image-as-context vs. canvas mode is unchanged.

A submission (text, photos, or both) either informs which catalog template gets picked (Mode 1: context, the default) or becomes the meme itself, captioned directly (Mode 2: canvas — "make this a meme"). If it actually contains several distinct meme-worthy moments (a long text dump, multiple photos), the system generates more than one meme instead of flattening everything into one. Each situation routes through an LLM intent-parsing layer (Ollama locally, Groq in production), does a RAG pre-filter over ~122 templates via ChromaDB, picks the best meme template, renders caption text onto the image using Pillow, and streams the result(s) back via SSE.

**Multimodal input invariant: ALL uploaded media enters through `backend/uploads/safe_ingest.py`'s `safe_ingest()` — never bypass it.** See `docs/UPLOADS.md` for the full pipeline and the "NLP / Vision & Uploads" section below for implementation details.

**Live demo:** frontend on Vercel (`memegpt-six.vercel.app`), backend on Render (`memegpt-backend.onrender.com`).

---

## Repository Layout

```
memegpt/
├── backend/                  FastAPI application (Python 3.11+)
│   ├── main.py               Entry point — mounts routers, CORS, static files, auto-seed on startup
│   ├── config.py             pydantic-settings Settings — LLM_PROVIDER, OLLAMA_*, GROQ_*, CORS, etc.
│   ├── schemas.py            Pydantic v2 models shared across all layers
│   ├── pyproject.toml        All Python dependencies + dev tooling config
│   │
│   ├── routers/
│   │   ├── chat.py           POST /chat/ (text) + POST /chat/image/ (Mode 1 context / Mode 2 canvas) — SSE stream
│   │   ├── explain.py        POST /explain/  — template metadata & history
│   │   ├── generate.py       POST /generate/ — on-demand meme generation
│   │   ├── feedback.py       POST /feedback/ — thumbs up/down, now recorded in Postgres (Growth Phase B)
│   │   ├── memes.py          GET /memes/{id} — share-page lookup, see "Growth Phase B" below
│   │   ├── me.py             DELETE /me/ — "Forget me", see "Growth Phase C" below
│   │   └── share_intake.py   POST /share-intake/ + GET /share-intake/{token}/ — PWA share-target
│   │                          stash/retrieve, see "Lore mode" below
│   │
│   ├── image_processing/
│   │   ├── compositor.py     Pillow text compositor (font loading, wrap, stroke) — renders to an
│   │   │                      in-memory buffer and hands off to storage/, doesn't touch disk directly
│   │   └── template_configs.py  Per-template TextBoxConfig layouts (29 explicit configs; the
│   │                              other ~93 of 122 templates fall back to DEFAULT_BOXES)
│   │
│   ├── storage/               Growth Phase B — save_meme() writes to R2 when configured, local
│   │                            static/generated/ disk otherwise. See "Growth Phase B" below.
│   ├── db/                    Growth Phase B — Postgres layer (memes/feedback/few_shot_examples/
│   │                            lore_lexicon), lazy asyncpg pool, schema.sql. See "Growth Phase B"
│   │                            and "Growth Phase C" below.
│   ├── identity.py            Growth Phase C — reads the X-MemeGPT-User header. See "Growth Phase C" below.
│   │
│   ├── vector_db/
│   │   ├── chroma_client.py  ChromaDB singleton — upsert, query, log_usage, dual-mode (local/HTTP)
│   │   └── examples_store.py Few-shot (prompt → meme) example collection — Postgres is now the
│   │                          source of truth (Growth Phase B), Chroma rehydrated from it on startup
│   │
│   ├── nlp/
│   │   ├── llm_client.py     call_llm() dispatches to Ollama (local) or Groq (cloud) — shared by
│   │   │                      intent_router.py and segmentation.py (extracted so both reuse one
│   │   │                      hardened dispatch/retry/JSON-cleanup implementation)
│   │   ├── intent_router.py  parse_intent() → IntentResponse JSON (template_id + captions)
│   │   ├── segmentation.py   Multi-context: resolve_contexts() splits one submission into 1..N
│   │   │                      meme-worthy situations — see "Segmentation" below
│   │   ├── lexicon.py        Growth Phase C — opt-in extract_lexicon(), see "Growth Phase C" below
│   │   └── vision.py         describe_image() (Mode 1: context) + generate_canvas_captions() (Mode 2:
│   │                          canvas) + infer_mode() — Groq (primary) / Anthropic (fallback) vision calls
│   │
│   ├── uploads/               Phase 0 safety gate — see docs/UPLOADS.md
│   │   ├── safe_ingest.py     safe_ingest() — the ONLY entry point for any uploaded image
│   │   ├── moderation.py      Content-safety check (reuses nlp/vision.py's Groq call + a safety rubric)
│   │   └── retention.py        TTL-tracked temp-file cleanup (forward-looking; not yet exercised)
│   │
│   ├── memory/
│   │   └── conversation_store.py  In-memory per-conversation template history (anti-repetition) —
│   │                                the in-memory half; Growth Phase C adds a DB-backed cross-session
│   │                                half in db/, see "Growth Phase C" below
│   │
│   ├── rate_limit.py          Shared slowapi Limiter instance (own module to avoid a main.py<->routers cycle)
│   ├── scripts/
│   │   └── eval_intent_models.py  Live A/B harness comparing Groq text models on JSON-parse
│   │                                reliability — see NLP / Intent Router below
│   ├── tests/                 pytest suite — Phase 0 safety tests, segmentation tests, multi-image
│   │                           batch tests, and a /chat/ text-flow regression test
│   ├── templates/            ~122 base meme images (JPG/PNG), named by template_id
│   ├── fonts/                Anton-Regular.ttf (downloaded at build time — free Impact equivalent)
│   ├── static/generated/     Runtime output — compositor writes PNGs here (ephemeral on Render)
│   ├── data/curated_examples.jsonl  Older 51-example few-shot set — see note below
│   ├── data/chroma/           ChromaDB persistent store (git-ignored)
│   ├── Dockerfile / .dockerignore
│   └── .env.example
│
├── frontend/                 Next.js 14 + Tailwind CSS (TypeScript)
│   └── src/
│       ├── app/
│       │   ├── layout.tsx    Root layout, dark theme, Inter font, PWA manifest link
│       │   ├── page.tsx      Public marketing landing page — <LandingPage /> — NOT the chat
│       │   │                  surface. Explains the product, links into /chat and /lore.
│       │   ├── chat/page.tsx Chat surface — <ModeTabs active="chat" /> + <ChatWindow />
│       │   ├── lore/page.tsx Lore surface — <ModeTabs active="lore" /> + <LoreView />; also the
│       │   │                  redirect target for share-target intake (?intake=<token>)
│       │   ├── m/[id]/page.tsx  Growth Phase B share page — generateMetadata for og:image/twitter:card,
│       │   │                     fetches GET /memes/{id} server-side, 404s via notFound() if unresolved
│       │   ├── share/route.ts  POST-only PWA share-target intake (NOT a page — Next.js disallows
│       │   │                    page.tsx + route.ts at the same segment). Relays the OS share
│       │   │                    sheet's multipart POST to the backend's /share-intake/, then
│       │   │                    303-redirects into /lore?intake=<token>. A stray GET redirects
│       │   │                    to /lore instead of erroring.
│       │   ├── api/chat/route.ts      App Router handler that proxies POST /chat/ with true SSE
│       │   │                          streaming — next.config.js `rewrites()` alone buffers the
│       │   │                          whole response and breaks SSE, so this route (checked
│       │   │                          before rewrites) takes precedence for this one path.
│       │   │                          export const maxDuration = 60 (multi-meme batches can run long)
│       │   ├── api/feedback/route.ts  Proxies POST /feedback/
│       │   └── globals.css   Tailwind directives + scrollbar + fadeIn animation
│       ├── hooks/
│       │   └── useMemeStream.ts  Shared SSE-accumulation logic (thinking/error/plan/loading state +
│       │                          submitText()/submitImages() returning {memes, plainReply}) — used
│       │                          by both ChatWindow and LoreView, presentation stays with the caller
│       ├── components/
│       │   ├── LandingPage.tsx   Public marketing page rendered at / — not part of the Chat/Lore
│       │   │                      tab pair, see "Landing page" design section below
│       │   ├── ModeTabs.tsx      Shared header + Chat|Lore tab toggle (URL is the source of truth
│       │   │                      for which surface is active, not client state)
│       │   ├── ChatWindow.tsx    Chat surface — flat running conversation, grouped chat bubbles
│       │   ├── LoreView.tsx      Lore surface — composer (textarea/drag-drop/count select) + a flat
│       │   │                      vertical feed where every meme gets its own permanently-visible card
│       │   ├── MessageBubble.tsx Per-message bubble (user right, bot left) — Chat only
│       │   ├── FeedbackButtons.tsx  Thumbs up/down, posts to /feedback/
│       │   ├── ShareButtons.tsx     Web Share API / copy-link for a generated meme
│       │   ├── ThinkingBubble.tsx   Renders the `thinking` SSE stage messages
│       │   └── MemeDisplay.tsx   next/image wrapper for rendered memes
│       ├── lib/
│       │   ├── api.ts         Typed fetch helpers: sendChatStream, sendChatImageStream, postFeedback,
│       │   │                   generateMeme, explainMeme, memeImageUrl, forgetMe
│       │   ├── identity.ts    Growth Phase C — getOrCreateAnonId()/forgetAnonId(), see "Growth Phase C" below
│       │   └── examplePrompts.ts  Pool of ~167 example prompts; pickRandomPrompts() draws 6 fresh
│       │                           per page load for Chat's empty-state chips
│       └── types/
│           └── index.ts       Shared TypeScript interfaces mirroring backend schemas
│
├── docker-compose.yml         Self-hosted stack: Ollama + ChromaDB + backend + frontend containers
├── render.yaml                Render.com Blueprint — native Python env, build/start commands
└── scripts/
    ├── seed_templates.py         Downloads Imgflip's top-100 templates + seeds ChromaDB (one-time bootstrap)
    ├── seed_examples.py          Manually seeds backend/data/curated_examples.jsonl (see note below)
    ├── ingest_imgflip_dataset.py / prepare_finetune_dataset.py / finetune_unsloth.py
    │                             Imgflip-100k → ChatML → Unsloth LoRA fine-tuning pipeline (not yet run)
    ├── Modelfile                 Ollama Modelfile for loading a finished fine-tuned GGUF
    ├── bridges2_job.sh / bridges2_ollama_service.sh / colab_ollama_server.ipynb / use_remote_ollama.sh
    │                             Remote GPU inference (PSC Bridges-2, Colab T4) for local dev
    └── dummy_template_test.py  Standalone Pillow PoC — run without any backend services
```

---

## Data Flow (per chat turn)

```
User types message (and/or attaches 1+ photos)
      │
      ▼
POST /chat/ or /chat/image/  (routers/chat.py)
      │
      ├─► [image only] uploads/safe_ingest.safe_ingest() per image, then nlp/vision.describe_image()
      │     per surviving image — produces plain-text situation descriptions
      │
      ├─► nlp/segmentation.resolve_contexts(text, image_descriptions, meme_count)
      │     └─ Fast path (zero LLM calls): one short message, or one photo, no explicit count
      │     └─ Otherwise: segment_contexts() finds 1..max_memes_per_request distinct situations
      │     └─ Returns: a plain list of situation strings, one per meme to generate
      │
      └─► _stream_batch(situations, conversation_id):
            │
            ├─► if len(situations) > 1: yield {"type": "plan", "situations": [...], "total": N}
            │     (skipped for a single situation — no "plan theater" for one meme)
            │
            SEQUENTIALLY, for each situation:
            │
            ├─► vector_db/chroma_client.query_similar_memes()
            │     └─ RAG pre-filter: top 8 semantically similar templates (keeps prompt ~1300 tokens)
            │
            ├─► nlp/intent_router.py parse_intent()
            │     └─ nlp/llm_client.call_llm() → Ollama or Groq
            │         └─ Returns: { template_id, texts: {box_label: caption}, reasoning }
            │         └─ template_id validated against known ChromaDB ids — rejects hallucinated ids, retries
            │
            ├─► image_processing/compositor.compose_meme()
            │     └─ Pillow: open template → per-box wrap/center text → draw 8-directional stroke → save PNG
            │         └─ Returns: "/static/generated/<id>.png"
            │
            └─► vector_db/chroma_client.log_usage()
                  └─ Appends usage event to template's ChromaDB metadata; add_turn() records the
                     template for THIS situation before the next one is parsed (see Segmentation below)

SSE events per situation: {"done", index, total, conversation_id, message: {content, meme_url}, template_used}
followed by one trailing {"batch_done", total, succeeded} once every situation has been attempted
      │
      ▼
Frontend (useMemeStream hook) accumulates all "done" events from one submission into
one {memes: MemeItem[], plainReply} result once the stream ends — Chat groups them into
one ChatMessage (1 meme = single card, 2+ = swipeable carousel); Lore appends each meme
as its own permanently-visible card to a flat feed instead
```

---

## Key Design Decisions

### Schemas (`schemas.py`)
- `TextBox` defines a bounding box in **pixel coordinates** relative to the template image. This allows templates to have arbitrary layouts (multi-panel, side-by-side) — not just top/bottom.
- `MemeTemplate.history` is a lightweight append-only list stored in ChromaDB metadata for now. Move to PostgreSQL once history grows beyond a few hundred entries per template.

### Image Compositor (`image_processing/compositor.py`)
- Font resolution order: `backend/fonts/Anton-Regular.ttf` → system paths (macOS Impact → Linux Anton/Liberation) → Pillow built-in fallback.
- Text wrapping uses `textwrap.wrap()` with a char-count estimate from `font.getlength("A")`, with an auto-shrink loop that reduces font size until the wrapped text fits the box height.
- Stroke is drawn as an 8-directional offset pass before the fill pass — classic meme rendering. `stroke_width = max(2, font_size // 12)`.
- Output is always PNG (lossless, supports transparency) regardless of input format.
- Per-template layouts live in `template_configs.py` — each template defines named `TextBoxConfig` boxes with their own coordinates, font size/color, and uppercase setting. Templates not in `TEMPLATE_CATALOG` fall back to `DEFAULT_BOXES` (classic top/bottom).
- Some templates already have text baked into the source image (e.g. `this_is_fine`'s "THIS IS FINE" speech bubble) — their configs only expose the box(es) that need new text, and `box_descriptions` tell the LLM not to repeat baked-in text.
- **Watermark + provenance (Growth master prompt Phase A):** `_draw_watermark(img)` draws a small `settings.watermark_text` ("memegpt" by default) bottom-right on EVERY generated meme — catalog templates (`compose_meme`), canvas mode (`compose_meme_on_image`), and `/generate/` (which calls `compose_meme` directly, so it's covered for free). Deliberately NOT a `TextBoxConfig` — it's drawn in its own `ImageDraw.Draw(img, "RGBA")` pass after all captions, independent of the box layout system, so it can never reposition or shrink a caption box. Font size `max(12, img_h * 3.5%)`, semi-transparent white fill with a thin dark stroke (`font_size // 14`, vs captions' `// 12` — deliberately subtler). Gated by `settings.watermark_enabled` (default true). **Known tightness, not yet fixed:** on `DEFAULT_BOXES` templates with a long bottom caption that fills the full-width box, the watermark can sit close to (though not overlapping/illegible with) the caption's last line, since both live in the same bottom strip of the image. Acceptable for now since it never obscures text; revisit if it looks worse on real captions than in testing.
- **Provenance tag:** every save also gets a PNG `tEXt` chunk (`memegpt_id`) via `PngInfo`, reusing the same per-render `uuid.uuid4().hex[:8]` already in the output filename — embedded unconditionally, independent of `watermark_enabled`, since it's invisible metadata rather than the visible brand mark that flag controls. Honest caveat: most platforms strip PNG metadata on re-encode (screenshots, most social re-uploads), so this is best-effort, not durable — the visible watermark is the one that actually survives circulation. Once Phase B introduces real durable `meme_id`s, this tag switches to that value.

### NLP / Intent Router (`nlp/intent_router.py`, `nlp/llm_client.py`)
- `nlp/llm_client.py`'s `call_llm()` dispatches to `call_groq()` (cloud, used in production via `LLM_PROVIDER=groq`) or `call_ollama()` (local dev, free, needs `ollama serve`) — extracted out of `intent_router.py` (pure refactor, no behavior change) so `nlp/segmentation.py` can reuse the same dispatch/retry/JSON-cleanup logic rather than duplicating it.
- **Production model:** `qwen/qwen3.6-27b` on Groq (llama-3.3-70b-versatile deprecated June 17 2026). Qwen 3.x thinking mode is disabled via `reasoning_effort: "none"` to prevent `<think>` tokens from breaking JSON parsing. `call_groq()` sets `reasoning_effort: "low"` for any `gpt-oss` model instead — Groq rejects `"none"` for that family (400: must be low/medium/high), and left unset it burns the whole `max_tokens` budget on hidden reasoning before ever emitting content, coming back empty.
- **`scripts/eval_intent_models.py`** — a live A/B harness comparing `qwen/qwen3.6-27b` against `openai/gpt-oss-120b` on JSON-parse success rate, valid-template-id rate, latency, and template diversity, run against the exact prompt-construction path `parse_intent()` uses. Verdict from a real run (paced to stay under Groq's free-tier ~8000 tokens/min limit, which a naive back-to-back loop blows through in ~10 requests): qwen's failures were all empty-response artifacts of rate-limiting (uniform ~10-12s latency matching the retry-then-give-up path in `call_groq()`), not genuine malformed output; gpt-oss-120b, even with the `reasoning_effort` fix, showed a real ~25%+ genuine `json_validate_failed` rate beyond rate-limit noise. **Kept `qwen/qwen3.6-27b` as the default** — the data didn't support switching.
- **RAG candidate-set resolution** lives in `resolve_prompt_template_ids()` — `query_similar_memes` finds the 8 most relevant templates via Gemini embeddings, merged with an 18-template core list (core templates listed first), capped at 25 total ids — keeps the prompt under token limits. Extracted out of `_parse_intent_inner()` into its own function specifically so `scripts/eval_template_matching.py` can call the exact live logic instead of hand-copying a snapshot that would silently drift whenever these parameters change.
- **Template catalog cleanup (2026-07-28):** found and removed 4 duplicate template pairs — the same source image saved under two different template_ids (`look_at_me`/`i_m_the_captain_now`, the two Bernie "once again asking" files, `is_this_a_pigeon`/`is_this_butterfly`, `bell_curve`/`midwit_bell_curve`) — via `scripts/find_duplicate_templates.py`, a two-pass sweep: perceptual image hashing (dHash, catches same-pixels-different-crop/format duplicates) and Gemini description-embedding similarity (catches same-meme-different-photo duplicates that dHash misses — confirmed live, one true duplicate pair scored only 0.605 on dHash but 0.864 on description similarity). Neither pass auto-deletes; both just rank candidates for a human look. 118 templates remain. Found and fixed a real latent bug along the way: Gemini's `batchEmbedContents` hard-caps at 100 items per call — `GeminiEmbeddingFunction._embed()` now chunks transparently so no caller (including this script, which embeds all 118 descriptions in one shot) has to know about the limit.
- **Template-matching accuracy eval — `scripts/eval_template_matching.py`.** Unlike `eval_intent_models.py` (JSON-parse reliability across providers, no ground truth), this has a labeled golden set (confusion-cluster cases plus cases targeting previously under-described templates) and reports two separate metrics: RAG recall (is an acceptable template_id in the candidate set `resolve_prompt_template_ids()` returns — a miss here is a retrieval problem) and final-pick accuracy (did `parse_intent()`'s actual choice match — a miss here despite correct retrieval is a wording/LLM-judgment problem). Baseline run (48 cases, real Groq + Gemini): **100% RAG recall, 75% final-pick accuracy** — confirming retrieval wasn't the bottleneck, so the `USE_WHEN` rewrite below was the right lever to pull first, not RAG parameter tuning.
- **`USE_WHEN` quality pass (2026-07-28) — including a real regression found and fixed via the eval harness, not just a straightforward win:** every one of the 118 templates now gets the same structured treatment that previously only the ~20 core templates had — a CAPS-label summary, a short "E.g." example, and explicit "NOT for X (use Y)" cross-references naming the specific templates it's most likely to get confused with. The confusable pairs found during the duplicate sweep (Leo pointing/toasting, the two Megamind entries, the two/three-way Spider-Man templates) got explicit disambiguation.
  - **First pass (two "E.g." examples per entry) measurably made matching WORSE, not better: 75% → 67%.** Diagnosis: 15 of 16 wrong picks (94%) landed on a core template — not random. Every entry getting 2-3x longer bloated the full 25-template prompt enough to bias the LLM toward the always-first, always-present core template block rather than correctly reading through to a more specific but less prominent match further down — a "lost in the middle" effect, not a wording-quality problem per se. A second, narrower bug also surfaced: `but_that_s_none_of_my_business`'s "tea-sipping" example collided with unrelated incidental wording in a test case, a reminder that added detail can create false keyword attractors.
  - **Fix: trimmed to one short example per entry**, recovering to ~72% (adjusted for a same-day embedding-backend confound, see below) — close enough to the 75% baseline to keep, given the real gains elsewhere (deduped catalog, disambiguated confusable pairs, full-catalog coverage instead of ~20 templates).
  - **This diagnosis surfaced during eval runs, not through data corrupted by rate-limiting** — `scripts/eval_template_matching.py` now captures `IntentResponse.reasoning` and flags any hard-fallback hit explicitly (excluded from the accuracy denominator), because an earlier run showed a false "23% accuracy" collapse that was actually `parse_intent()`'s hardcoded fallback firing on nearly every case from Groq rate-limit exhaustion, not genuine wrong picks — the fallback's `template_id` is indistinguishable from a real (bad) pick without checking `reasoning`.
  - **Gemini's free tier has a 1000 requests/day cap** (confirmed live), separate from the 100/minute limit — this session's repeated full-catalog reseeds + eval runs exhausted it in one day. Unlike the per-minute limit, no short retry gets past it. Local iteration on wording (independent of which embedding backend is active) can route around this entirely by running with `GEMINI_API_KEY=` unset — falls back to ChromaDB's local model, zero quota use, near-instant reseed. The final trimmed-description numbers above were measured this way once the daily quota was exhausted; RAG recall was 96% on local embeddings vs 100% on Gemini for the same golden set (expected — Gemini's embeddings are the stronger model), so final-pick-accuracy numbers across the two runs aren't a perfectly clean apples-to-apples comparison, just a good-enough read given the constraint.
  - **A related production reliability bug found and fixed along the way:** `GeminiEmbeddingFunction`'s retry budget (up to 61s across 6 retries, sized for background seeding) was being reused by the *live* RAG query path too — but `parse_intent()`'s entire request has only a 45s budget. A Gemini rate-limit blip on the live query path could burn the whole request timeout on RAG retries alone, starving the Groq LLM call before it ever ran. Fixed by splitting the retry budget: `__call__` (documents — seeding, upsert on feedback, background-only) keeps the patient 6-retry/61s budget; `embed_query` (the live `/chat/` RAG lookup) now uses a short 2-retry/~3s budget and fails fast to its existing `[]`-degrades-gracefully path instead.
  - **Phase 4 (RAG retrieval parameter tuning) — evidence-based conclusion: no changes.** With RAG recall already at 96-100%, there's very little headroom for retrieval tuning to help. Checked directly: the two cases that missed retrieval under local embeddings didn't rank anywhere in the top 20 candidates (one dead last, one absent entirely) — raising `n_results` from 8 wouldn't have caught either one; they're genuinely poor semantic matches under a weaker embedding model, not near-miss cases sitting just outside the cutoff. Since production runs on Gemini (already 100% recall on this golden set) and a larger candidate set directly feeds the exact prompt-bloat problem diagnosed above, there's no evidence-backed case for changing `query_similar_memes`'s `n_results` (8), `get_similar_examples`'s `n_results` (3), or the 25-item prompt cap — left as-is.
- Response is parsed via `json.loads()` + `_normalize_llm_response()` (handles common LLM JSON format deviations) + Pydantic validation.
- Both the primary parse attempt and the retry each wrap the full `_call_llm()` + parse chain in `try/except (json.JSONDecodeError, ValidationError, ValueError, KeyError, httpx.HTTPError)` — this ensures `httpx.HTTPError` from network failures can't bypass the hard fallback.
- **`template_id` is validated against the known ChromaDB id set on both the primary and retry attempt** — if the LLM hallucinates an id not in the catalog, it's rejected and retried rather than passed to the compositor (which would 404).
- Hard fallback (`hide_the_pain_harold`) guarantees `parse_intent` never raises to the caller.
- **Bounded to 45s total (`_OVERALL_TIMEOUT_SECONDS`, `asyncio.wait_for`)** — found via live testing against production: a pathological run where both the primary AND retry attempts hit 429s (each internally retrying once inside `call_groq()`) compounded past 90s with zero SSE events reaching the frontend past the initial "thinking" message, no fallback, just an indefinite hang. `parse_intent()`'s actual body moved into `_parse_intent_inner()`; the public function wraps it and returns the same hard fallback (reasoning: "timed out before producing a result") on `asyncio.TimeoutError` instead of hanging. `nlp/segmentation.py`'s `segment_contexts()` got the identical treatment (same `call_llm` dispatch, same risk shape) — its existing broad `except Exception` already catches `asyncio.TimeoutError` for free, so that one only needed the `asyncio.wait_for` wrapper, no new except branch.
- `USE_WHEN` dict: every template_id maps to a structured description (see the quality pass above) including NOT-FOR language naming specific alternatives — prevents common confusion clusters (drake/evil_kermit/two_buttons, distracted_boyfriend/left_exit_12/uno_draw_25_cards, leonardo_dicaprio_cheers/laughing_leo, spiderman_pointing_at_spiderman/spider_man_triple, megamind_no_bitches/megamind_peeking, etc.).

### Segmentation — multi-context, multi-meme generation (`nlp/segmentation.py`)
- **`resolve_contexts(text, image_descriptions, requested_count)`** is the only function other code calls — it owns the trigger policy and returns a plain `list[str]`, one situation per meme to generate. **Fast path (zero LLM calls, identical to pre-segmentation behavior):** a short message (< `segmentation_text_threshold_chars`, default 240) with fewer than 2 images and no explicit count override. `requested_count == 1` always forces the fast path too, even over long text or several images — there's no reason to pay for a segmentation call whose only valid output is one context.
- Otherwise, **`segment_contexts()`** makes one structured-JSON LLM call (via `nlp/llm_client.py` — pure text-in/JSON-out, same shape as `parse_intent()`, so no reason to restrict it to vision-capable providers the way `nlp/vision.py` does) asking for 1..`max_memes_per_request` (default 5) distinct meme-worthy moments. **Never raises** — any failure (network, malformed JSON, anything) degrades to a single context built from a plain concatenation of the input, i.e. exactly what happened before segmentation existed.
- If `requested_count` is set and the LLM finds fewer distinct moments than asked for, the dominant one is **repeated** to pad out the count — deliberately, rather than inventing synthetic variations. This works because `_stream_batch` (below) runs situations **sequentially**: each repeat's `parse_intent(..., avoid_templates=recent)` sees the *previous* repeat's just-picked template via `conversation_store`'s existing recency tracking, so repeats naturally land on different templates/captions for free, with zero new plumbing.
- **`routers/chat.py`'s `_stream_batch()`** runs `_stream_chat_turn()` once per resolved situation, in sequence (not parallel — deliberately, for the diversity-via-avoid_templates property above), yielding every event as it happens so memes appear progressively. A failure on one situation (`parse_intent`/`compose_meme` raising) only ends that situation's sub-stream; the batch continues to the next one. A trailing `{"type": "batch_done", "total": N, "succeeded": M}` event closes every stream, whether it ran one situation or several.
- **`chat_with_image()`** now accepts `images: list[UploadFile]` (capped at `max_images_per_request`, default 6). Each image is safety-checked independently (`asyncio.gather`); a **content-moderation failure on ANY image aborts the whole request** with the existing generic refusal (a moderation hit is an adversarial signal, and skip-and-continue would leak a per-image "this one got silently dropped" signal that `uploads/moderation.py`'s category-never-echoed invariant exists to prevent) — but a non-safety `UploadRejected` (too big, wrong type) on one image just drops that image and continues with the survivors. If every image is dropped this way but text was also provided, the request degrades to a text-only turn rather than hard-refusing; if there's no text either, `_upload_rejection_message()` maps the specific `UploadRejected.reason` (file too large, unrecognized type, dimensions too large, corrupt file) to friendly, specific text — safe to be specific here since none of these reasons carry an adversarial signal, unlike moderation's category.
- **`_stream_batch()` emits a `{"type": "plan", "situations": [...], "total": N}` event** immediately before rendering the first situation, but only when `N > 1` — decided entirely inside `_stream_batch` (`len(situations) <= 1` suppresses it), no signal needed from `resolve_contexts` itself. Fires identically for `/chat/` and `/chat/image/`'s context-mode path since both funnel through this one function; `_stream_canvas_batch` (canvas mode) is untouched, since the plan event is a segmentation-path concept. Lore renders this as a checklist ticking off as `"done"` events land (keyed by `index`); Chat ignores it (minimal chrome).
- **`max_dump_chars` (default 20000, `config.py`)** bounds pasted text — `_clamp_dump_text()` truncates (never rejects) `message` in both routes before it ever reaches `resolve_contexts`, logging a debug-level note (lengths only, never the text) when clamping actually fires. Lore's composer shows a matching client-side notice past the same threshold; the real enforcement is server-side.

### Vision & Uploads (`nlp/vision.py`, `uploads/`) — Phase 0 + Phase 1 of multimodal input
- **Invariant: `uploads/safe_ingest.py`'s `safe_ingest()` is the only entry point for any uploaded image.** Pipeline in order: streamed size cap (10MB, doesn't trust `Content-Length`) → magic-byte type sniffing (hand-rolled signature dict, never trusts the extension or client-supplied MIME type — deliberately skips `python-magic` to avoid a new system `libmagic` dependency Render's native build has no precedent for) → Pillow decompression-bomb guard (`Image.MAX_IMAGE_PIXELS` + an explicit >8000px-per-side check) → metadata stripping (rebuilds a fresh `Image` via `Image.frombytes()`, guaranteeing an empty `.info` dict — no EXIF/GPS can survive) → content moderation.
- **Never writes the original upload to disk** — everything happens in memory. `uploads/retention.py` ships a TTL-tracked cleanup utility (`tracked_temp_file()`, `purge_expired()`, a periodic sweep started in `main.py`'s lifespan) as forward-looking infrastructure for Phase 3 (video), which will need a real file for ffmpeg; it's not exercised by anything today.
- **Moderation (`uploads/moderation.py`) deliberately does NOT use a dedicated Llama-Guard-style model.** Its exact request/response contract on Groq couldn't be live-verified (no `GROQ_API_KEY` available at implementation time), and shipping against an unverified contract risks silently failing *open*. Instead it reuses `nlp/vision.py`'s already-verified Groq vision call with a strict safety rubric — exactly the master prompt's documented fallback. Fails **closed** (rejects) on any provider error or missing config — an inability to moderate is treated as a failed moderation check, never a pass-through.
- **No same-provider vision fallback exists today (checked live, not just assumed):** `qwen/qwen3.6-27b` is currently the *only* vision-capable model on Groq's API — `groq/compound`, `groq/compound-mini`, and `llama-3.3-70b-versatile` all reject multi-part/image content (text-only), and both `meta-llama/llama-4-maverick-17b-128e-instruct` and `-scout` 404 ("does not exist or you do not have access to it"). Anthropic remains the only fallback tier. Revisit if Groq's model lineup changes.
- **`nlp/vision.py`'s `describe_image(image: PIL.Image.Image, ...)`** takes a raw Pillow image (not the `uploads.safe_ingest.CleanImage` wrapper — callers pass `clean.image`, keeping `vision.py` decoupled from the `uploads/` package and avoiding a circular import, since `uploads/moderation.py` also reuses this module's low-level Groq call). Primary: Groq `qwen/qwen3.6-27b` — the *same model* `intent_router.py` already uses for text routing, so this needs zero new provider account. Optional fallback: Anthropic `claude-sonnet-5` via raw `httpx` (no SDK, matching this repo's existing style), gated on `ANTHROPIC_API_KEY` being set. Raises `VisionUnavailable` if both fail — unlike `parse_intent()`, there's no safe hardcoded fallback description, so the caller degrades to asking the user to describe the photo in words.
- **`POST /chat/image/`** (in `routers/chat.py`) is a sibling route to `POST /chat/`, not a retrofit of it — FastAPI routes bind to one body type, and this keeps the existing JSON `/chat/` contract provably unchanged. Both routes resolve into a `list[str]` of situations (via `nlp/segmentation.py`) and hand them to the same `_stream_batch()` → `_stream_chat_turn()` sequence (analyzing → `parse_intent` → rendering → `compose_meme` → `log_usage` → done). **`parse_intent()` and `compositor.py` needed zero changes** — every situation, vision-derived or not, is just a plain string fed into the same `parse_intent(user_message, ...)` call `/chat/` always made.
- Rate-limited via `slowapi` (`backend/rate_limit.py` holds the shared `Limiter` instance in its own module specifically to avoid a `main.py` ↔ `routers/chat.py` circular import) — currently scoped to `/chat/image/` only, not yet applied to `/chat/`.
- Phase 3 (video) is not yet implemented; see `memegpt-multimodal-master-prompt.md` for scope.

### Canvas mode — Mode 2 of multimodal input (`nlp/vision.py`, `routers/chat.py`)
- **The user's own photo becomes the meme directly** (captioned top/bottom), instead of being described and matched to a catalog template (Mode 1). Selected via `nlp/vision.py`'s `infer_mode(message)` — a cheap keyword check (`"make this a meme"`, `"meme this"`, etc.), computed ONCE per request from the shared message text (not per image — every photo in a batch shares the same accompanying text) — or an explicit `mode: "context"|"canvas"` form field on `/chat/image/` that overrides inference; an invalid/unrecognized `mode` value is silently ignored rather than rejecting the request, falling through to keyword inference.
- **`nlp/vision.py`'s `generate_canvas_captions(image, user_text)`** makes ONE vision call asking directly for `{"top_text", "bottom_text"}` JSON, rather than a separate describe-then-caption round trip — the caption writer sees the actual pixels, not a lossy paraphrase, and it's half the latency/cost. Uses `call_groq_vision()`'s new optional `response_format` param (`{"type": "json_object"}`) to get Groq's JSON mode; `describe_image()`'s and `moderate_image()`'s existing plain-text calls are unaffected since they don't pass it. **Returns `None` on any failure** (network, malformed JSON, missing keys) rather than raising — a caller `asyncio.gather`-ing several of these can just filter out the `None`s.
- **`image_processing/compositor.py`'s `compose_meme_on_image(image, texts)`** reuses `DEFAULT_BOXES` (already generic/percentage-based) against the caller's own photo instead of looking up a catalog `template_id`, and reuses `_resolve_font`/`_draw_text_in_box` unchanged. Draws a **translucent dark scrim** behind each caption box before the text pass — arbitrary user photos have no hand-tuned safe zone the way catalog templates do (nearly every non-`DEFAULT_BOXES` entry in `template_configs.py` exists specifically because generic placement doesn't work for that image's composition), so the scrim guarantees legibility regardless of what's underneath, at effectively zero cost. Scoped to this function only — `compose_meme()`'s catalog-template rendering is untouched.
- **`routers/chat.py`'s `_stream_canvas_batch()`/`_stream_canvas_turn()`** mirror `_stream_batch()`/`_stream_chat_turn()`'s shape but skip RAG, `parse_intent`, `add_turn`, and `log_usage` entirely — none of those concepts apply (no template_id, no repetition to avoid since each meme is on a unique photo, and `log_usage` is keyed by catalog template_id in ChromaDB). `template_used` stays `None` in the response (already `Optional[str]`; the frontend already tolerates a falsy `templateId`). A per-image caption failure just drops that image and continues with survivors (same "drop and continue" precedent as `UploadRejected`); if every caption call fails, degrades to the same graceful text-reply pattern used when Mode 1's vision calls all fail. **`meme_count` is ignored in canvas mode** — its semantics don't transfer (canvas mode's meme count is already fixed by how many photos survived ingestion, not a separately requested synthetic split).
- **No frontend UI for the mode override** — reachable only via the `mode` form field for direct API use. Keyword inference is the only exposed mechanism; a toggle is premature before there's usage data on how often it misfires. Canvas-mode memes need zero frontend changes otherwise — they're just `MemeItem`s with `templateId: undefined`, flowing through the exact same carousel/feedback machinery as any other meme.

### Vector DB (`vector_db/chroma_client.py`)
- **Embedding backend: Gemini API when `GEMINI_API_KEY` is set, ChromaDB's default local model (`all-MiniLM-L6-v2`) otherwise.** ChromaDB's default embedding function loads a sentence-transformers/ONNX model in-process — empirically measured (fresh-deploy simulation, real RSS tracking) at ~491MB peak during template seeding alone, which OOM-crashed `memegpt-backend` on Render's 512MB free tier after a single meme generation. `vector_db/gemini_embedding_function.py`'s `GeminiEmbeddingFunction` offloads embedding compute to Gemini's `gemini-embedding-2` API instead (raw httpx, no `google-genai` SDK — matches this repo's existing no-SDK style for Groq/Anthropic/vision), so that model never loads on Render. Local dev stays zero-config/zero-cost by default (no key set → local model, unchanged from before this change); a developer can opt into the Gemini path locally by setting `GEMINI_API_KEY` in `backend/.env`, but must then delete `backend/data/chroma/` once first — Gemini's 3072-dim vectors aren't compatible with the local model's existing 384-dim ones, and ChromaDB is already treated as rebuildable-from-seed. `get_embedding_function(settings)` is called from both `chroma_client.py::init_chroma()` and `examples_store.py::_get_collection()`; when it returns `None` the `embedding_function=` kwarg is omitted entirely (not passed as `None`) so ChromaDB's real default — a class instance, not `None` — takes over exactly as before.
- **Document-vs-query task-type asymmetry, for free:** ChromaDB's `Collection.query(query_texts=...)` calls the embedding function's `embed_query()` when defined, falling back to `__call__()` otherwise. `GeminiEmbeddingFunction` implements both — `__call__()` (used for `upsert`/`upsert_templates_batch`/`upsert_example`) tags requests `RETRIEVAL_DOCUMENT`, `embed_query()` (used automatically by every `query_similar_memes()`/`get_similar_examples()` call) tags them `RETRIEVAL_QUERY` — with zero changes needed at any call site. Both go through one `batchEmbedContents` HTTP call per invocation (works for both a full batch and a single query).
- **Resilience:** `query_similar_memes()` and `get_similar_examples()` now wrap their `col.query(...)` call in try/except, returning `[]` on failure instead of raising — this closes a gap the Gemini swap would otherwise have opened: `intent_router.py`'s `parse_intent()` is documented as never raising to the caller (hard fallback to `hide_the_pain_harold`), but its `try/except` only wraps the `call_llm()` + JSON-parse chain, not the RAG calls above it. That was a dormant gap when embedding was local and effectively infallible; moving it to a network call made it real. With an empty RAG/examples result, `parse_intent()` still has the 18-item core template list to work with, so a Gemini blip degrades match quality for one request instead of breaking it.
- **Non-blocking:** `GeminiEmbeddingFunction.__call__`/`embed_query` are synchronous (required by ChromaDB's `EmbeddingFunction` protocol), so `intent_router.py`'s two RAG call sites run through `await asyncio.to_thread(...)` — otherwise the Gemini round-trip (~100-400ms) would block the event loop for every other concurrent request being served by the same process, not just the one making the call.
- **Startup seeding trips Gemini's rate limit on a cold start — expected, and handled.** `gemini-embedding-2`'s free tier is capped at 100 requests/minute; empirically confirmed live, each text in a `batchEmbedContents` call counts individually toward that budget, so a single `_SEED_CHUNK_SIZE=20` chunk (`main.py::_auto_seed_if_empty()`) can burn a fifth of the window by itself, and the first chunk of a fresh ~122-template seed reliably 429s. `GeminiEmbeddingFunction._post_with_429_retry()` retries with capped exponential backoff (1, 2, 4, 8, 16, 30s — 61s total across 6 attempts) specifically sized to outlast a full 60s rate-limit window; there's no per-chunk try/except upstream in `_auto_seed_if_empty()`'s loop, so without this, one rate-limited chunk would crash the entire seed and leave the app on the small hardcoded `_FALLBACK_TEMPLATES` list until the next restart happens to get lucky. Cheap to retry generously here since this only ever runs in a background thread or via `asyncio.to_thread` — never blocking a live request. Verified end-to-end against the real API: a fresh local seed (empty `data/chroma/`) rode out the full retry window on template seeding, then correctly matched real `/chat/` prompts (`waiting_skeleton` for a Friday-afternoon code-review wait, `grus_plan` for a plan-gone-wrong-at-the-last-step message) — not the hardcoded fallback.
- **Data-flow / privacy note:** every `/chat/` message and Lore-mode dump (up to `max_dump_chars`) is sent to Gemini for embedding when the Gemini path is active — the same text already sent to Groq for LLM intent-routing, now also seen by a second external processor for the RAG similarity search. No new persistent storage is involved (this is a transient per-request call, not a new write path), and the growth spec's "never store/log raw dump text" non-negotiable is untouched. Checked both providers' actual terms: Groq's no-training policy is account-wide (free tier included), no human review of API data; Gemini's **free** tier allows Google to use submitted content to improve products and permits human review — only Gemini's paid tier removes both. This tradeoff was disclosed to and knowingly accepted by the project owner, who chose to stay on the free tier; revisit if this product's data-sensitivity bar changes (e.g. Lore mode sees heavier real-world use with more identifiable content).
- Dual-mode client: `PersistentClient` for local dev / Render (embedded, no `CHROMA_HOST`), `HttpClient` when `CHROMA_HOST` is set (Docker Compose).
- `main.py` auto-seeds all templates found in `backend/templates/` on startup if the collection is empty — no manual seed step needed for a fresh deploy.
- Seeding is **sequential** (templates first, then few-shot examples via `examples_store.seed_examples()`). Concurrent ChromaDB embedding model loads spiked past Render's 512MB free-tier limit; serialized into `_sequential_seed()` run in a single background thread.
- `usage_count` and `recent_uses` are stored as metadata fields (not documents) so they survive re-embedding without touching the document text.
- Few-shot examples seeded into a separate ChromaDB collection by `examples_store.py` — 15 curated (prompt → template) pairs covering the most abstract/confusable templates, auto-seeded on startup via `seed_examples()`.
- **Known duplication:** `backend/data/curated_examples.jsonl` (51 older examples, popular templates) is a second, disconnected few-shot source seeded only by manually running `scripts/seed_examples.py`. It predates the 15-item hardcoded set and the two have no defined relationship — running the script adds to, rather than replaces, the auto-seeded set.
- **Image-embedding template retrieval (CLIP/SigLIP2 via Hugging Face) — investigated, not viable, do not re-attempt without re-checking:** Hugging Face's free serverless Inference API no longer hosts *any* CLIP/SigLIP-family model, on any provider, free or paid — confirmed live via `GET /api/models/openai/clip-vit-base-patch32?expand[]=inferenceProviderMapping`, which returns an empty mapping, and via `GET /api/models?pipeline_tag=zero-shot-image-classification&inference_provider=hf-inference`, which returns zero results. The legacy `api-inference.huggingface.co` domain (the one most docs/tutorials still reference) doesn't even resolve anymore — HF has moved to `router.huggingface.co`, but the model category this feature needed simply isn't deployed there. Getting real image embeddings would require running weights in-process, which violates the zero-Render-footprint constraint that made this worth trying in the first place. Revisit only if HF's provider lineup changes.

### Frontend (`frontend/`)
- `next.config.js` rewrites `/api/*` → `process.env.BACKEND_URL` (defaults to `localhost:8000`) so the frontend never hardcodes the backend URL in component code. `remotePatterns` allow image loading from `localhost`, the Docker `backend` hostname, and `*.onrender.com`.
- **`app/api/chat/route.ts` overrides the generic rewrite for `/chat/`** — Next.js checks the filesystem for a matching route before applying `rewrites()`, and `rewrites()` buffers the entire upstream response before forwarding, which breaks SSE. The route handler pipes the backend's `ReadableStream` straight through instead.
- **Image uploads (`sendChatImageStream` in `lib/api.ts`) POST directly to `NEXT_PUBLIC_API_BASE`/chat/image/`, bypassing the Vercel proxy entirely** — there used to be an `app/api/chat/image/route.ts` doing the same raw-body-passthrough trick as `app/api/chat/route.ts`, but Vercel serverless functions hard-cap request bodies at 4.5MB regardless of what the FastAPI backend allows, and multiple photos blow past that easily (413s the whole request). Going straight to the backend avoids the limit entirely; it's safe because CORS is already wide open in production (`CORS_ALLOW_ALL_ORIGINS=true`, see `render.yaml`) and `NEXT_PUBLIC_API_BASE` is already guaranteed browser-reachable in every topology (local dev, Docker Compose's baked-in build arg, and Render/Vercel) — the same guarantee `memeImageUrl()` already relies on for loading rendered meme images.
- Tailwind brand color palette uses shades 50–900 (all must be defined; missing shades like 400 cause Vercel build failures if referenced in CSS).
- `memeImageUrl()` in `lib/api.ts` prefixes relative meme URLs with `process.env.NEXT_PUBLIC_API_BASE` (must be set in Vercel for production; falls back to `localhost:8000` for local dev).
- Conversation state (`conversationId`) is held in `useMemeStream`'s state — intentionally ephemeral, resets on page refresh.
- Backend-side conversation memory (`backend/memory/conversation_store.py`) tracks the last 5 template ids per `conversation_id` and feeds them to `parse_intent(..., avoid_templates=...)` so the LLM is nudged away from repeating the same template within a session.
- **`ChatMessage.memes?: MemeItem[]`** — one array, always, rather than a singular `meme_url`/`template_id` (which would let code checking only the singular field silently render a multi-meme reply as if it had none). `MessageBubble.tsx` (Chat only) renders `memes.length === 1` as a single card, `2+` as an `overflow-x-auto snap-x snap-mandatory` horizontal carousel (no new npm dependency — native touch-swipe/scroll) with a dot indicator and one `FeedbackButtons` docked to the in-view card (`activeIndex`, tracked via a scroll handler).
- **Each `MemeItem.situationText`** carries the specific segmented context that produced that meme (the backend populates `ChatMessage.content` with the situation text instead of always `""`). Both surfaces' `handleFeedback` use this — not the shared original user submission — as the few-shot example key, because `vector_db/examples_store.py`'s `upsert_example` hashes purely on message text: without this, two different memes from the same multi-meme batch would collide on the same ChromaDB doc id and silently overwrite each other's feedback.

### Lore mode — two-surface restructure (`hooks/useMemeStream.ts`, `LoreView.tsx`, `ModeTabs.tsx`, share-target)
- **Naming map:** "Chat" and "Lore" are public-facing names only. Internally, both surfaces call the exact same `/chat/`/`/chat/image/` endpoints and the exact same segmentation/batch/canvas machinery documented above — there is no separate backend for Lore. The one place "Lore" leaks into backend code at all is `max_dump_chars` (a Lore-composer-sized paste ceiling, enforced for both routes regardless of which surface sent the request).
- **`useMemeStream()`** (new shared hook) owns the transient SSE-submission state (`thinking`/`error`/`plan`/`loading`/`conversationId`) and the accumulation logic — every `"done"` event's meme collects locally across the stream, and `submitText()`/`submitImages()` return `{memes, plainReply}` once the stream ends. It does **not** own a message/feed list: Chat groups a submission's memes into one `ChatMessage` bubble; Lore appends each meme as its own permanently-visible card to a flat feed. This is a deliberate difference — Lore's feed shows every meme from a submission simultaneously (no swiping needed to reach any of them, and giving feedback on one never hides the others), unlike Chat's carousel.
- **`ModeTabs.tsx`** — the URL (`/chat` vs `/lore`) is the source of truth for which surface is active, not client state; this is what makes `/lore` a genuine bookmarkable/shareable deep link. `/` is a separate public marketing landing page (`LandingPage.tsx`), not one of the two tabs — see "Landing page" below.
- **Chat is intentionally simplified UI-only**: no meme-count `<select>` (always auto-detect) — but the `/chat/`/`/chat/image/` API contracts keep every capability; a Chat user who pastes something long still gets auto-segmented into multiple memes, just without an explicit override control. The count `<select>` (Auto/2-5), the auto-growing textarea, and the drag-and-drop zone all live in `LoreView.tsx` instead.
- **PWA share-target**: `manifest.json`'s `share_target` (`action: "/share"`, `method: "POST"`, `enctype: "multipart/form-data"`) lets the OS share sheet (primarily Android Chrome) hand MemeGPT shared images/text directly. `app/share/route.ts` is a **route handler, not a page** (Next.js disallows both at one segment) — it relays the multipart POST server-to-server to the backend's new `POST /share-intake/`, which stashes the payload in memory keyed by a single-use token (same "no locks needed, one persistent event loop" precedent as `memory/conversation_store.py`) and responds with the token; the route then 303-redirects to `/lore?intake=<token>` per the Web Share Target spec (a redirect, not a body, avoids a duplicate POST on refresh). **The stash deliberately lives on the backend (Render, one persistent instance), not in the Vercel-hosted frontend's route handler** — Vercel gives no guarantee that two requests moments apart hit the same serverless instance/module scope, so an in-memory `Map` there would be unreliable in a way it isn't on Render. `LoreView.tsx` reads `?intake=` from `window.location.search` on mount (not `next/navigation`'s `useSearchParams()`, which would force this otherwise-statically-prerendered page into a Suspense boundary), fetches `GET /share-intake/{token}/` once, decodes each image's base64 back into a `File`, and pre-fills the composer — **never auto-submits** — then strips the query param. Stashed images are **not** moderated/sanitized at stash time; that stays exactly at real `/chat/image/` submission time, so a user can remove a shared image before ever paying that cost.
- **iOS Safari has more limited PWA share-target support** than Android Chrome (which is why the primary verification target is Android Chrome) — not fought here; if iOS share-target support matters later, revisit then rather than blocking this feature on it now.

### Landing page (`app/page.tsx`, `components/LandingPage.tsx`)
- **`/` is a public marketing page, not the app itself** — it explains what MemeGPT is (hero, "how it works", Chat vs Lore explainer) and links into `/chat` and `/lore`, which is why the chat surface moved from `/` to its own `/chat` route (see "Frontend" above). This mirrors the pattern most AI product sites use (a stateless explainer page in front of the actual tool) rather than dropping a first-time visitor straight into an empty chat box with no context.
- Uses `motion` (the current package name for what was `framer-motion` — same team, same API, `framer-motion` is now just an alias at the same version) for scroll-triggered reveals (`whileInView`, fade + slide up, staggered per section) and a handful of real meme template thumbnails (`public/landing/*.jpg`, copied from `backend/templates/` at build time, not runtime) gently floating in the hero background — continuous slow drift + rotation, not scroll-triggered, to read as "alive" without being distracting.
- **Copy is deliberately written without em dashes** — a specific ask, followed throughout the page's actual visible text (code comments are unaffected).
- `manifest.json`'s `start_url` points at `/chat`, not `/` — an installed PWA should open straight into the app on subsequent launches, not the marketing page every time.

### Growth Phase B — durable storage + share pages (`storage/`, `db/`, `routers/memes.py`, `app/m/[id]/page.tsx`)
`memegpt-growth-master-prompt.md` (repo root) is a 7-phase growth roadmap (A–G: watermark, durable storage, anonymous memory, Wrapped, trend pipeline, fine-tune prep, Discord distribution). Phase A (watermark), Phase B (this section), and Phase C (anonymous memory, see below) are done; D–G are not started. The spec requires a written plan per phase, approved before code, and "ask for exactly the credentials that phase needs, not all upfront" — Phase B needed Supabase (`DATABASE_URL`) and Cloudflare R2 creds, gathered at that point, not before; Phase C needed no new credentials, reusing Phase B's `DATABASE_URL`.

- **The problem this solves:** before Phase B, generated memes lived only on Render's ephemeral disk (`static/generated/`, gone on every restart/redeploy) and feedback/few-shot examples lived only in ChromaDB, treated as rebuildable-from-seed — meaning real user feedback was silently lost on every redeploy. Zero-cost constraint held throughout: R2's free tier (10GB, no egress fees) and Supabase's free Postgres tier, both feature-flagged with graceful absence — unset creds mean local disk + no persistence, the fully-functional default, never a crash.

- **`storage/`'s `save_meme(png_bytes, meme_id=None) -> SavedMeme`** picks R2 (boto3 S3-compatible client, `_r2_configured()` requires ALL five R2 settings present, never a partial fallback) or local disk (writes into the same `static/generated/` directory as before) based on config alone. `SavedMeme(meme_id, url, path)` — `path` is `None` exactly when stored on R2 (nothing local to serve). `meme_id` generation lives here too: `secrets.choice()` (CSPRNG, not `random`) over base62, 10 chars — replacing Phase A's temporary `uuid.uuid4().hex[:8]`, exactly as Phase A's own docstring promised. One id now serves three purposes: the storage object key, the PNG provenance `tEXt` tag, and the Postgres `memes.id` primary key.

- **`compositor.py`'s `compose_meme()`/`compose_meme_on_image()` now render into an in-memory `io.BytesIO()` buffer** instead of saving straight to disk, and return `SavedMeme` instead of the old `Union[str, Path]` + `return_path: bool` toggle — a deliberate breaking change to the internal return type. The external HTTP/SSE wire contract (`meme_url: str` in JSON responses) is unchanged, so this needed zero frontend changes on its own. `generate.py`'s `GET /generate/file/{template_id}` (a debug convenience endpoint, not part of the product surface) switches from `FileResponse` to a redirect when `SavedMeme.path` is `None` (R2 active) — `FileResponse` only when local disk is active, which is true in every test environment and any deployment without R2 creds.

- **`db/`'s `get_pool()`** (asyncpg, raw SQL, no ORM — matches this repo's established minimalism of raw `httpx` over SDKs everywhere else) returns `None` when `settings.database_url` is empty; every read/write function in `db/__init__.py` checks this and no-ops gracefully. Schema (`db/schema.sql`, three tables: `memes`, `feedback`, `few_shot_examples`) is applied idempotently (`CREATE TABLE IF NOT EXISTS`) on first real connection — no Alembic, matching the "no redesign, keep it simple" pattern for a 3-table schema.

- **PRIVACY RULE (confirmed with user, since the spec's own wording was ambiguous):** `memes` and `feedback` never store situation text, dump text, or captions — ids and metadata only. `few_shot_examples` is the deliberate exception: storing `(user_message, template_id, texts)` is its entire purpose, and it's replacing an already-existing ChromaDB store with the same content, not new exposure. The two other tables' schemas reflect this literally — `memes` has no text column beyond `url`/`template_id`, `feedback` has no `user_message`/`texts` columns at all.

- **`log_usage()`'s call site in `chat.py`** (both `_stream_chat_turn` and `_stream_canvas_turn`) also calls `db.insert_meme()` now — canvas mode included, since canvas-mode memes need `/m/{id}` share pages too, even though it still skips `log_usage`/`add_turn` (those are Chroma-specific, keyed by catalog `template_id`, which canvas mode has none of).

- **`feedback.py` now records EVERY rating unconditionally** (`db.insert_feedback`, both up and down) — fixing a real pre-existing gap where 👎 was silently discarded entirely (the docstring said "logged but not stored" but nothing was even logged). 👍 with a message still additionally calls `upsert_example()` for the few-shot store, unchanged in spirit. `meme_id` now flows end-to-end: compositor → SSE `done` event → `ChatMessage.meme_id` → frontend `MemeItem.memeId` → `FeedbackButtons` → `FeedbackRequest.meme_id`, so feedback attributes to a specific durable meme instead of fuzzy `template_id` + `user_message` matching.

- **`examples_store.py`'s `upsert_example()` is now async** and dual-writes ChromaDB (semantic retrieval at request time) and Postgres (source of truth, survives redeploys) using the same id (`_example_id()` — sha256 of the normalized message, extracted as a shared helper). **`seed_examples()`** checks Postgres first: real rows there (meaning real usage has occurred and persisted) get rehydrated into Chroma, taking priority over the 15-item hardcoded seed list, which only bootstraps a genuinely fresh/empty Postgres. Both callers (`routers/feedback.py`, the standalone `scripts/seed_examples.py`) updated for the signature change.

- **`main.py`'s `_sequential_seed()`** (the existing background-thread seeding function, deliberately sequential with template seeding to avoid concurrent Chroma embedding-model memory spikes on Render's free tier) now wraps `seed_examples()` in `asyncio.run(...)` — `seed_examples()` is async (it may fetch Postgres rehydration rows before writing to Chroma) but the thread itself has no event loop of its own, so this gives it one just for that call, then the thread continues synchronously as before.

- **`GET /memes/{id}` (`routers/memes.py`)** returns `{url, template_name}` only — `response_model=SharedMemeResponse` structurally prevents anything else from leaking even if `db.fetch_meme()` somehow returned more. 404s whenever `db.fetch_meme()` returns `None` — which is the same response whether `DATABASE_URL` is unset or the id genuinely doesn't exist, no distinction leaked to the caller. Rate-limited (`"30/minute"`, generous vs. the upload path's `"5/minute"` since this is a cheap read) using the exact `@limiter.limit` + `request: Request` pattern already established in `chat.py`. **No listing endpoint exists anywhere in this app, ever** — this is a single lookup by a specific, unguessable (base62, CSPRNG) id, the only way in.

- **`app/m/[id]/page.tsx`** is the first use of Next.js's async `generateMetadata` in this repo (previously only `layout.tsx`'s static `metadata` export existed). Fetches `GET {BACKEND_URL}/memes/{id}` server-side (matching the existing `route.ts` convention — `BACKEND_URL` may be a Docker-internal/localhost address) for both `generateMetadata` (og/twitter tags) and the page body — Next.js automatically dedupes identical `fetch()` calls within one render pass, so this is one real network call per request despite two call sites. The `og:image`/`twitter:image` URL embedded in the HTML is whatever `save_meme()` returned (already a public R2 URL or Render's public `/static/` URL) — crawlers fetch `og:image` directly and aren't subject to `next.config.js`'s `remotePatterns` restriction at all (that only gates `next/image`'s optimizer, which this page also bypasses via `unoptimized`, matching `MemeDisplay.tsx`'s existing pattern). 404s via `notFound()` when the backend returns 404. Minimal page chrome deliberately (logo, meme, one "Make your own" CTA into `/chat`) rather than the Chat/Lore nav — this page is for external visitors arriving from a shared link, not app navigation. Verified end-to-end against real R2 + Supabase: generated a real meme, confirmed the row landed in Postgres via direct query, confirmed `curl`'d raw HTML contains correct `og:image`/`og:title`/`twitter:card` tags pointing at the real public R2 URL, visually confirmed the served image renders correctly with the watermark.

### Growth Phase C — anonymous identity + memory v1 (`identity.py`, `nlp/lexicon.py`, `routers/me.py`, `frontend/src/lib/identity.ts`)
A lightweight, no-signup memory layer built on top of Phase B's Postgres tables. Landed as 4 commits (identity plumbing → humor profile/cross-session avoid_templates → opt-in Lore lexicon → forget-me), each independently green against the test suite.

- **Identity**: the frontend generates a UUID once into `localStorage` (`memegpt_uid`, `lib/identity.ts`'s `getOrCreateAnonId()` — read fresh at every call site, never cached in a module variable, which is what makes Forget-me trivially correct) and sends it as `X-MemeGPT-User` on every chat/image/feedback call. Backend reads it via `identity.py`'s `get_anon_user_id(request) -> str | None` — absent header, blank value, or no `Request` in scope all degrade to `None`, and every consumer treats `None` as "no personalization," never an error. **`memes.anon_user_id` already existed in the schema since Phase B** (speced there, just never populated) — this phase is what finally writes to it.
- **The two hand-written Next.js proxy routes needed a real fix, not just `lib/api.ts`**: `app/api/chat/route.ts` and `app/api/feedback/route.ts` build their own `fetch()` to the backend (bypassing `next.config.js`'s generic `rewrites()`, which is what makes them exist at all — see the SSE-streaming note above), so they don't forward inbound headers automatically. Both now explicitly read `req.headers.get("x-memegpt-user")` and re-attach it on their outbound `fetch()`. `/me/` needed no such fix — it has no hand-written route, so it rides the generic rewrite, which forwards headers transparently.
- **Cross-session avoid_templates**: `memory/conversation_store.py`'s existing in-memory, per-`conversation_id` tracking is untouched — it still updates turn-to-turn within one batch. A new DB-backed half, `db.fetch_recent_templates_for_user(anon_user_id, n=5)`, is fetched once per request batch (it doesn't change mid-request) and merged with the in-memory list (dedup, in-memory first) before reaching `parse_intent`.
- **Humor profile**: `db.fetch_humor_profile(anon_user_id)` aggregates `feedback` by `template_id`/`rating` (which required adding `anon_user_id` AND `template_id` columns to `feedback` — the latter fixes a real pre-existing gap where `FeedbackRequest.template_id` was read off every request and silently dropped before persistence, never mind Phase C). Gated behind a minimum-signal threshold (≥3 total ratings, ≥2 same-direction ratings on a template to count) so one stray downvote can't skew a profile; returns `None` (not empty lists) below threshold. Feeds `parse_intent()` as a new `humor_block`, built the identical "conditional paragraph, then `.format()`" way the existing `avoid_block` already is — explicitly phrased as "a light nudge, never a hard rule." Skipped on the retry prompt, matching `avoid_block`/`few_shot_block`'s existing retry-exempt precedent.
- **`db.PersonalizationContext`** (`anon_user_id`, `avoid_templates`, `loved_templates`, `hated_templates`, `lexicon`) + `fetch_personalization(anon_user_id)` bundle all of the above into one dataclass, fetched via one `asyncio.gather` (three independent indexed reads, so this adds one round-trip of latency ahead of `parse_intent`, not three) — same "small data-bag next to the function that produces it" pattern already used for `CleanImage`/`SavedMeme`. A fresh all-empty instance (never shared/cached) when there's no anon id, so every caller in `routers/chat.py` can read its fields unconditionally. Threaded through `_stream_batch`/`_stream_chat_turn`; canvas mode only ever needed the bare `anon_user_id` (it never touches `parse_intent`/`resolve_contexts`).
- **Lore lexicon — strictly opt-in, default off**: a "🧠 Remember lore" toggle in `LoreView.tsx`'s composer (sticky across a session's submissions, not reset per-message — "remember this whole conversation," not "remember this one message"). When on, `nlp/lexicon.py`'s `extract_lexicon()` makes one structured-JSON `call_llm()` call (same shape as `segment_contexts()`) asking for up to 15 short recurring names/nicknames/running-joke phrases — never raises, degrades to `[]` on any failure. Runs via `schedule_lexicon_extraction()`, a fire-and-forget `asyncio.create_task()` held in a module-level `set()` with a `add_done_callback` to discard on completion (the standard fix for a background task otherwise being eligible for garbage collection mid-flight, since nothing else holds a reference to it) — extraction never adds latency to the SSE response. Stored via `db.upsert_lexicon()` into a new one-row-per-user `lore_lexicon` table (terms accumulate via a Python-side merge + case-insensitive dedupe + cap at 40, not a jsonb SQL expression — deliberately simple since this only ever runs off the hot path).
- **Extraction and injection are decoupled on purpose**: extraction (the LLM call + store) only runs when *this* request's `remember_lore` is true. Injection — reading an already-stored lexicon into `resolve_contexts`/`segment_contexts`/`parse_intent` — runs on *every* request for that user regardless of this request's toggle state, so past callbacks keep landing even on a request where the toggle happens to be off. Lexicon terms reach the LLM **only** through the system-prompt instruction channel (`intent_router.py`'s new `lexicon_block`, `segmentation.py`'s new `lexicon_instruction`) — never through `_build_material`'s content channel, never into `user_message`/situation text — which is what keeps extracted phrases from leaking into anything later persisted via `ChatMessage.content` or a thumbs-up few-shot example.
- **Forget me**: `DELETE /me/` (`routers/me.py`, rate-limited `"5/minute"`) reads the anon id and calls `db.delete_anon_user_data()`, which runs inside one transaction — the first multi-statement write in `db/__init__.py`, justified because partial deletion on a user-initiated erase is worse than all-or-nothing failure. Deletes `feedback` before `memes`: `feedback.meme_id REFERENCES memes(id)` has no `ON DELETE` clause (defaults to RESTRICT), so deleting a still-referenced `memes` row first would fail with a FK violation; the delete's `OR meme_id IN (...)` clause covers both feedback rows this user posted directly and feedback (from anyone) attached to a meme this user generated. **200, not 404, when no header is sent** — there's no "resource" to fail to find, matching every other `db.py` function's absence-is-a-no-op contract. A small "Forget me" text control lives in `ModeTabs.tsx`'s shared header (the one chrome component visible from both Chat and Lore) — `window.confirm()` → `forgetMe()` → `forgetAnonId()` (clears `localStorage`) → `window.location.reload()`; the next request just generates a fresh id, no other invalidation needed anywhere since `identity.ts` never caches it.
- **Degrades cleanly with no `DATABASE_URL`** by construction, not by a separate verification pass — every new `db.py` function follows the pre-existing "`pool = await get_pool(); if pool is None: return <empty>`" contract, and the test suite already runs with no `DATABASE_URL` set by default.

### Deployment
- **Backend (Render):** native Python runtime (`env: python` in `render.yaml`), not Docker — the service must be configured this way in Settings if created manually through the dashboard, since render.yaml service-type changes don't apply retroactively to manually-created services. Build command installs deps + downloads Anton font. `LLM_PROVIDER=groq` + `GROQ_API_KEY` env var for cloud inference (Render's CPU-only free tier can't run Ollama at usable speed). The same `GROQ_API_KEY` also powers Phase 1 vision + moderation calls and segmentation — no new required env var for the multimodal or multi-meme features to work; `ANTHROPIC_API_KEY` is optional (vision fallback only). **Growth Phase B's `DATABASE_URL` + 5 `R2_*` vars are also optional** — unset means local disk storage and no Postgres persistence, not a broken deployment; `render.yaml` doesn't declare them since they're meant to be added manually in the dashboard when/if durable storage is wanted, same `sync: false` pattern as `GROQ_API_KEY`. When setting `DATABASE_URL` from Supabase, use the **Connection String** (starts `postgresql://`), not the **Project URL** (starts `https://`) — easy to mix up, and pydantic-settings' strict validation will reject a stray non-matching env var name if the placeholder text gets pasted as its own line instead of substituted into the connection string.
- **Frontend (Vercel):** needs `BACKEND_URL` (server-side rewrites) and `NEXT_PUBLIC_API_BASE` (client-side image URLs **and** direct image-upload POSTs, see above) pointed at the Render backend URL. `app/api/chat/route.ts` sets `export const maxDuration = 60` — a multi-meme batch generates sequentially and can plausibly take 15-40s end-to-end, worse right after Render's cold-start. Image uploads aren't subject to this at all since they never touch a Vercel function.
- Render free tier spins down after 15 min idle — first request after idle takes ~30s to wake up.
- **`MAINTENANCE_MODE=true`** (Vercel env var, optional, unset by default): `frontend/src/middleware.ts` rewrites every route to `/maintenance` — a self-contained coming-soon page (dark purple/pink/cyan glow theme, 6 rotating headlines, 50 real pre-generated gag memes drifting across in lanes) — while a revamp is in progress. `NextResponse.rewrite()`, not redirect, so the real URL stays in the address bar. Toggling requires a redeploy (env var changes aren't picked up live). The 50 images (`frontend/public/maintenance/*.png`) come from `scripts/generate_maintenance_memes.py`, which reuses the real compositor but monkeypatches its `save_meme` binding to write locally only — real R2/Postgres credentials in `.env` are never touched, since these are throwaway gag assets, not real product data.

---

## Remaining Implementation Work

### Medium Priority
- [ ] **User-uploaded templates**: `POST /templates/upload` endpoint — accept an image, extract dominant color palette, generate a `template_id`, write to `backend/templates/`, upsert into ChromaDB.
- [x] **Conversation history**: `backend/memory/conversation_store.py` tracks recent template ids per conversation and passes them to `parse_intent` as `avoid_templates` to reduce repetition. (Full prior-message context, not just template ids, is still not passed back.)
- [x] **Durable chatbot memory**: raised 2026-07-24, zero-cost constraint — something that persists across sessions/conversations, not just the existing ephemeral per-conversation template tracking above. This is Growth master prompt Phase C ("anonymous identity + memory v1") — anon UUID header, a humor profile fed into `parse_intent`, an opt-in Lore lexicon, a `DELETE /me` endpoint. See "Growth Phase C" above for the full design.
- [ ] **Fine-tuned model**: scripts for LoRA fine-tuning on the Imgflip 100k dataset exist (`scripts/finetune_unsloth.py`) but training hasn't been run.

### Low Priority / Polish
- [x] **Rate limiting** (`slowapi`): implemented, but currently scoped only to `/chat/image/` (the upload path). Extending it to plain-text `/chat/` is still pending.
- [x] **Tests**: `backend/tests/` now exists (first test suite in the repo) — Phase 0 upload safety-gate tests, `nlp/segmentation.py` trigger-policy/fallback tests, multi-image batch tests, and a `/chat/` text-flow regression test via `httpx.AsyncClient`. Still missing: `compositor.py` golden-image-diff tests and `intent_router.py` Groq/Ollama mock tests.
- [x] **Multi-context, multi-meme generation**: a long text dump or several photos can now produce more than one meme per submission (`nlp/segmentation.py`, `_stream_batch` in `routers/chat.py`), with an explicit `meme_count` override. Generation is deliberately sequential, not parallel — see the Segmentation design-decision note above for why; parallelizing while preserving the avoid-templates diversity property is a valid future optimization if latency on large batches becomes a real complaint.
- [x] **Multimodal Phase 2 (canvas mode)**: the user's own photo can become the meme directly (top/bottom captions) instead of always matching a catalog template — see "Canvas mode" above. v2 stretch (face-detection-aware placement) not started.
- [ ] **Multimodal Phase 3 (video)**: blocked — see `FEASIBILITY.md`. ffmpeg availability on Render's native runtime is confirmed; whether the app can process a video within a request's realistic time budget on the free tier (vs. needing a background-job architecture nothing in this codebase uses yet) is not, and needs either a timing probe against the live deployment or an upfront architecture decision before design resumes.
- [x] **Lore mode (two-surface restructure)**: Chat and Lore now split minimal-chrome chatbot vs. explicit-controls big-context-dump into two public surfaces sharing one backend — see "Lore mode" above. Covers the mode toggle, a shared `useMemeStream` hook, a "plan" SSE event, PWA share-target intake, and a paste-size guard (`max_dump_chars`). Skipped as an explicit stretch: a "use my photos as the memes" (canvas) toggle in Lore's composer — still reachable only via the `mode` API form field, no UI control yet.
- [x] **Public landing page**: `/` no longer drops visitors straight into the chat UI — see "Landing page" above. Chat moved to `/chat`.
- [x] **Model evaluation tooling**: `scripts/eval_intent_models.py` is a live A/B harness for comparing Groq text models — see "NLP / Intent Router" above for the qwen3.6-27b vs gpt-oss-120b findings. Also investigated (and ruled out for now) a same-provider vision fallback and HF-based image-embedding retrieval — see "Vision & Uploads" and "Vector DB" above.
- [x] **Growth master prompt Phase A (watermark)**: every generated meme gets a small brand mark + PNG provenance tag — see "Image Compositor" above.
- [x] **Growth master prompt Phase B (durable storage + share pages)**: R2 object storage with local-disk fallback, Postgres as source of truth for memes/feedback/few-shot examples (fixing real data loss on every Render redeploy), `/m/{id}` share pages with Open Graph tags — see "Growth Phase B" above. Verified end-to-end against the real Supabase + R2 instances, not just mocked tests.
- [x] **Growth master prompt Phase C (anonymous identity + memory v1)**: no-signup anon id, cross-session template memory, a feedback-derived humor profile, an opt-in Lore lexicon for callback humor, and a Forget-me control that erases everything — see "Growth Phase C" above. Phases D–G (Wrapped, trend pipeline, fine-tune prep, Discord distribution) not started.
- [ ] **Generated image persistence**: Render's filesystem is ephemeral — `static/generated/` PNGs are lost on restart/redeploy. Fine for live chat, not for durable sharing of past memes.

---

## Local Development Quickstart

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Local LLM (free, default) — separate terminal:
ollama pull llama3.1:8b && ollama serve

# OR cloud LLM (no GPU needed):
export LLM_PROVIDER=groq
export GROQ_API_KEY=gsk_...

uvicorn main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
# Templates auto-seed into ChromaDB on first startup if empty.
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

### Pillow PoC (no services needed)
```bash
cd memegpt/
pip install Pillow
python scripts/dummy_template_test.py
# → scripts/dummy_output.png
```
