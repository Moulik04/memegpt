# MemeGPT — System Documentation

## Overview

MemeGPT is a chatbot that communicates exclusively through memes. There are two public frontend surfaces sharing one backend: **Chat** (`/`) — a normal chatbot, the catch is it only replies in memes — and **Lore** (`/lore`) — for big context dumps: paste a whole group-chat thread, upload a stack of screenshots, get several memes back, with explicit controls (meme count, drag-and-drop) that Chat deliberately doesn't expose. "Lore" is a purely public-facing/UI name; internally everything still runs through the same segmentation → batch → SSE machinery described below, and the master-prompt-era "Phase 1/Phase 2" language for image-as-context vs. canvas mode is unchanged.

A submission (text, photos, or both) either informs which catalog template gets picked (Mode 1: context, the default) or becomes the meme itself, captioned directly (Mode 2: canvas — "make this a meme"). If it actually contains several distinct meme-worthy moments (a long text dump, multiple photos), the system generates more than one meme instead of flattening everything into one. Each situation routes through an LLM intent-parsing layer (Ollama locally, Groq in production), does a RAG pre-filter over ~110 templates via ChromaDB, picks the best meme template, renders caption text onto the image using Pillow, and streams the result(s) back via SSE.

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
│   │   ├── feedback.py       POST /feedback/ — thumbs up/down logging to ChromaDB
│   │   └── share_intake.py   POST /share-intake/ + GET /share-intake/{token}/ — PWA share-target
│   │                          stash/retrieve, see "Lore mode" below
│   │
│   ├── image_processing/
│   │   ├── compositor.py     Pillow text compositor (font loading, wrap, stroke)
│   │   └── template_configs.py  Per-template TextBoxConfig layouts (100 templates)
│   │
│   ├── vector_db/
│   │   ├── chroma_client.py  ChromaDB singleton — upsert, query, log_usage, dual-mode (local/HTTP)
│   │   └── examples_store.py Few-shot (prompt → meme) example collection
│   │
│   ├── nlp/
│   │   ├── llm_client.py     call_llm() dispatches to Ollama (local) or Groq (cloud) — shared by
│   │   │                      intent_router.py and segmentation.py (extracted so both reuse one
│   │   │                      hardened dispatch/retry/JSON-cleanup implementation)
│   │   ├── intent_router.py  parse_intent() → IntentResponse JSON (template_id + captions)
│   │   ├── segmentation.py   Multi-context: resolve_contexts() splits one submission into 1..N
│   │   │                      meme-worthy situations — see "Segmentation" below
│   │   └── vision.py         describe_image() (Mode 1: context) + generate_canvas_captions() (Mode 2:
│   │                          canvas) + infer_mode() — Groq (primary) / Anthropic (fallback) vision calls
│   │
│   ├── uploads/               Phase 0 safety gate — see docs/UPLOADS.md
│   │   ├── safe_ingest.py     safe_ingest() — the ONLY entry point for any uploaded image
│   │   ├── moderation.py      Content-safety check (reuses nlp/vision.py's Groq call + a safety rubric)
│   │   └── retention.py        TTL-tracked temp-file cleanup (forward-looking; not yet exercised)
│   │
│   ├── memory/
│   │   └── conversation_store.py  In-memory per-conversation template history (anti-repetition)
│   │
│   ├── rate_limit.py          Shared slowapi Limiter instance (own module to avoid a main.py<->routers cycle)
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
│       │   ├── page.tsx      Chat surface — <ModeTabs active="chat" /> + <ChatWindow />
│       │   ├── lore/page.tsx Lore surface — <ModeTabs active="lore" /> + <LoreView />; also the
│       │   │                  redirect target for share-target intake (?intake=<token>)
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
│       │   └── api.ts         Typed fetch helpers: sendChatStream, sendChatImageStream, postFeedback,
│       │                       generateMeme, explainMeme, memeImageUrl
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

### NLP / Intent Router (`nlp/intent_router.py`, `nlp/llm_client.py`)
- `nlp/llm_client.py`'s `call_llm()` dispatches to `call_groq()` (cloud, used in production via `LLM_PROVIDER=groq`) or `call_ollama()` (local dev, free, needs `ollama serve`) — extracted out of `intent_router.py` (pure refactor, no behavior change) so `nlp/segmentation.py` can reuse the same dispatch/retry/JSON-cleanup logic rather than duplicating it.
- **Production model:** `qwen/qwen3.6-27b` on Groq (llama-3.3-70b-versatile deprecated June 17 2026). Qwen 3.x thinking mode is disabled via `reasoning_effort: "none"` to prevent `<think>` tokens from breaking JSON parsing. `call_groq()` sets `reasoning_effort: "low"` for any `gpt-oss` model instead — Groq rejects `"none"` for that family (400: must be low/medium/high), and left unset it burns the whole `max_tokens` budget on hidden reasoning before ever emitting content, coming back empty.
- **`scripts/eval_intent_models.py`** — a live A/B harness comparing `qwen/qwen3.6-27b` against `openai/gpt-oss-120b` on JSON-parse success rate, valid-template-id rate, latency, and template diversity, run against the exact prompt-construction path `parse_intent()` uses. Verdict from a real run (paced to stay under Groq's free-tier ~8000 tokens/min limit, which a naive back-to-back loop blows through in ~10 requests): qwen's failures were all empty-response artifacts of rate-limiting (uniform ~10-12s latency matching the retry-then-give-up path in `call_groq()`), not genuine malformed output; gpt-oss-120b, even with the `reasoning_effort` fix, showed a real ~25%+ genuine `json_validate_failed` rate beyond rate-limit noise. **Kept `qwen/qwen3.6-27b` as the default** — the data didn't support switching.
- RAG pre-filter (`query_similar_memes`) finds the 8 most relevant templates, merged with an 18-template core list (core templates listed first), capped at 25 — keeps the prompt under token limits.
- Response is parsed via `json.loads()` + `_normalize_llm_response()` (handles common LLM JSON format deviations) + Pydantic validation.
- Both the primary parse attempt and the retry each wrap the full `_call_llm()` + parse chain in `try/except (json.JSONDecodeError, ValidationError, ValueError, KeyError, httpx.HTTPError)` — this ensures `httpx.HTTPError` from network failures can't bypass the hard fallback.
- **`template_id` is validated against the known ChromaDB id set on both the primary and retry attempt** — if the LLM hallucinates an id not in the catalog, it's rejected and retried rather than passed to the compositor (which would 404).
- Hard fallback (`hide_the_pain_harold`) guarantees `parse_intent` never raises to the caller.
- `USE_WHEN` dict: each template_id maps to a terse description including NOT-FOR language naming specific alternatives — prevents common confusion clusters (drake/evil_kermit/two_buttons, distracted_boyfriend/left_exit_12/uno_draw_25_cards, etc.).

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
- ChromaDB uses its default embedding model (`all-MiniLM-L6-v2`) — no external embedding API key required.
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
- **`ModeTabs.tsx`** — the URL (`/` vs `/lore`) is the source of truth for which surface is active, not client state; this is what makes `/lore` a genuine bookmarkable/shareable deep link.
- **Chat is intentionally simplified UI-only**: no meme-count `<select>` (always auto-detect) — but the `/chat/`/`/chat/image/` API contracts keep every capability; a Chat user who pastes something long still gets auto-segmented into multiple memes, just without an explicit override control. The count `<select>` (Auto/2-5), the auto-growing textarea, and the drag-and-drop zone all live in `LoreView.tsx` instead.
- **PWA share-target**: `manifest.json`'s `share_target` (`action: "/share"`, `method: "POST"`, `enctype: "multipart/form-data"`) lets the OS share sheet (primarily Android Chrome) hand MemeGPT shared images/text directly. `app/share/route.ts` is a **route handler, not a page** (Next.js disallows both at one segment) — it relays the multipart POST server-to-server to the backend's new `POST /share-intake/`, which stashes the payload in memory keyed by a single-use token (same "no locks needed, one persistent event loop" precedent as `memory/conversation_store.py`) and responds with the token; the route then 303-redirects to `/lore?intake=<token>` per the Web Share Target spec (a redirect, not a body, avoids a duplicate POST on refresh). **The stash deliberately lives on the backend (Render, one persistent instance), not in the Vercel-hosted frontend's route handler** — Vercel gives no guarantee that two requests moments apart hit the same serverless instance/module scope, so an in-memory `Map` there would be unreliable in a way it isn't on Render. `LoreView.tsx` reads `?intake=` from `window.location.search` on mount (not `next/navigation`'s `useSearchParams()`, which would force this otherwise-statically-prerendered page into a Suspense boundary), fetches `GET /share-intake/{token}/` once, decodes each image's base64 back into a `File`, and pre-fills the composer — **never auto-submits** — then strips the query param. Stashed images are **not** moderated/sanitized at stash time; that stays exactly at real `/chat/image/` submission time, so a user can remove a shared image before ever paying that cost.
- **iOS Safari has more limited PWA share-target support** than Android Chrome (which is why the primary verification target is Android Chrome) — not fought here; if iOS share-target support matters later, revisit then rather than blocking this feature on it now.

### Deployment
- **Backend (Render):** native Python runtime (`env: python` in `render.yaml`), not Docker — the service must be configured this way in Settings if created manually through the dashboard, since render.yaml service-type changes don't apply retroactively to manually-created services. Build command installs deps + downloads Anton font. `LLM_PROVIDER=groq` + `GROQ_API_KEY` env var for cloud inference (Render's CPU-only free tier can't run Ollama at usable speed). The same `GROQ_API_KEY` also powers Phase 1 vision + moderation calls and segmentation — no new required env var for the multimodal or multi-meme features to work; `ANTHROPIC_API_KEY` is optional (vision fallback only).
- **Frontend (Vercel):** needs `BACKEND_URL` (server-side rewrites) and `NEXT_PUBLIC_API_BASE` (client-side image URLs **and** direct image-upload POSTs, see above) pointed at the Render backend URL. `app/api/chat/route.ts` sets `export const maxDuration = 60` — a multi-meme batch generates sequentially and can plausibly take 15-40s end-to-end, worse right after Render's cold-start. Image uploads aren't subject to this at all since they never touch a Vercel function.
- Render free tier spins down after 15 min idle — first request after idle takes ~30s to wake up.

---

## Remaining Implementation Work

### Medium Priority
- [ ] **User-uploaded templates**: `POST /templates/upload` endpoint — accept an image, extract dominant color palette, generate a `template_id`, write to `backend/templates/`, upsert into ChromaDB.
- [x] **Conversation history**: `backend/memory/conversation_store.py` tracks recent template ids per conversation and passes them to `parse_intent` as `avoid_templates` to reduce repetition. (Full prior-message context, not just template ids, is still not passed back.)
- [ ] **Fine-tuned model**: scripts for LoRA fine-tuning on the Imgflip 100k dataset exist (`scripts/finetune_unsloth.py`) but training hasn't been run.

### Low Priority / Polish
- [x] **Rate limiting** (`slowapi`): implemented, but currently scoped only to `/chat/image/` (the upload path). Extending it to plain-text `/chat/` is still pending.
- [x] **Tests**: `backend/tests/` now exists (first test suite in the repo) — Phase 0 upload safety-gate tests, `nlp/segmentation.py` trigger-policy/fallback tests, multi-image batch tests, and a `/chat/` text-flow regression test via `httpx.AsyncClient`. Still missing: `compositor.py` golden-image-diff tests and `intent_router.py` Groq/Ollama mock tests.
- [x] **Multi-context, multi-meme generation**: a long text dump or several photos can now produce more than one meme per submission (`nlp/segmentation.py`, `_stream_batch` in `routers/chat.py`), with an explicit `meme_count` override. Generation is deliberately sequential, not parallel — see the Segmentation design-decision note above for why; parallelizing while preserving the avoid-templates diversity property is a valid future optimization if latency on large batches becomes a real complaint.
- [x] **Multimodal Phase 2 (canvas mode)**: the user's own photo can become the meme directly (top/bottom captions) instead of always matching a catalog template — see "Canvas mode" above. v2 stretch (face-detection-aware placement) not started.
- [ ] **Multimodal Phase 3 (video)**: blocked — see `FEASIBILITY.md`. ffmpeg availability on Render's native runtime is confirmed; whether the app can process a video within a request's realistic time budget on the free tier (vs. needing a background-job architecture nothing in this codebase uses yet) is not, and needs either a timing probe against the live deployment or an upfront architecture decision before design resumes.
- [x] **Lore mode (two-surface restructure)**: Chat and Lore now split minimal-chrome chatbot vs. explicit-controls big-context-dump into two public surfaces sharing one backend — see "Lore mode" above. Covers the mode toggle, a shared `useMemeStream` hook, a "plan" SSE event, PWA share-target intake, and a paste-size guard (`max_dump_chars`). Skipped as an explicit stretch: a "use my photos as the memes" (canvas) toggle in Lore's composer — still reachable only via the `mode` API form field, no UI control yet.
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
