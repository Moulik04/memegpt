# MemeGPT — System Documentation

## Overview

MemeGPT is a chatbot that communicates exclusively through memes. A user sends a plain-English message (or, as of Phase 1 of multimodal input, a photo); the system routes it through an LLM intent-parsing layer (Ollama locally, Groq in production), does a RAG pre-filter over ~110 templates via ChromaDB, picks the best meme template, renders caption text onto the image using Pillow, and streams the result back to a React/Next.js chat interface via SSE.

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
│   │   ├── chat.py           POST /chat/ (text) + POST /chat/image/ (Phase 1 multimodal) — SSE stream
│   │   ├── explain.py        POST /explain/  — template metadata & history
│   │   ├── generate.py       POST /generate/ — on-demand meme generation
│   │   └── feedback.py       POST /feedback/ — thumbs up/down logging to ChromaDB
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
│   │   ├── intent_router.py  _call_llm() dispatches to Ollama (local) or Groq (cloud) → IntentResponse JSON
│   │   └── vision.py         Phase 1: describe_image() — Groq (primary) / Anthropic (fallback) vision call
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
│   ├── tests/                 pytest suite — Phase 0 safety tests + a /chat/ text-flow regression test
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
│       │   ├── page.tsx      Single-page entry — renders <ChatWindow />
│       │   ├── share/page.tsx  Share-target landing page (PWA `manifest.json` + Web Share API)
│       │   ├── api/chat/route.ts      App Router handler that proxies POST /chat/ with true SSE
│       │   │                          streaming — next.config.js `rewrites()` alone buffers the
│       │   │                          whole response and breaks SSE, so this route (checked
│       │   │                          before rewrites) takes precedence for this one path
│       │   ├── api/chat/image/route.ts  Same idea, but passes the multipart body through RAW
│       │   │                            (not req.json()) — forwards req.body + Content-Type with
│       │   │                            duplex:"half" straight to POST /chat/image/
│       │   ├── api/feedback/route.ts  Proxies POST /feedback/
│       │   └── globals.css   Tailwind directives + scrollbar + fadeIn animation
│       ├── components/
│       │   ├── ChatWindow.tsx    Stateful chat container, SSE consumer, conversation ID
│       │   ├── MessageBubble.tsx Per-message bubble (user right, bot left)
│       │   ├── FeedbackButtons.tsx  Thumbs up/down, posts to /feedback/
│       │   ├── ShareButtons.tsx     Web Share API / copy-link for a generated meme
│       │   ├── ThinkingBubble.tsx   Renders the `thinking` SSE stage messages
│       │   └── MemeDisplay.tsx   next/image wrapper for rendered memes
│       ├── lib/
│       │   └── api.ts         Typed fetch helpers: sendChatStream, generateMeme, explainMeme, memeImageUrl
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
User types message
      │
      ▼
POST /chat/  (routers/chat.py) — SSE stream: thinking → rendering → done
      │
      ├─► vector_db/chroma_client.query_similar_memes()
      │     └─ RAG pre-filter: top 8 semantically similar templates (keeps prompt ~1300 tokens)
      │
      ├─► nlp/intent_router.py parse_intent()
      │     └─ _call_llm() → Ollama (LLM_PROVIDER=ollama) or Groq (LLM_PROVIDER=groq)
      │         └─ Returns: { template_id, texts: {box_label: caption}, reasoning }
      │         └─ template_id validated against known ChromaDB ids — rejects hallucinated ids, retries
      │
      ├─► image_processing/compositor.compose_meme()
      │     └─ Pillow: open template → per-box wrap/center text → draw 8-directional stroke → save PNG
      │         └─ Returns: "/static/generated/<id>.png"
      │
      └─► vector_db/chroma_client.log_usage()
            └─ Appends usage event to template's ChromaDB metadata

Response (SSE "done" event): { conversation_id, message: { role, content, meme_url }, template_used }
      │
      ▼
Frontend resolves meme_url via memeImageUrl() → NEXT_PUBLIC_API_BASE + relative path
<MemeDisplay /> renders the image with next/image
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

### NLP / Intent Router (`nlp/intent_router.py`)
- `_call_llm()` dispatches to `_call_groq()` (cloud, used in production via `LLM_PROVIDER=groq`) or `_call_ollama()` (local dev, free, needs `ollama serve`).
- **Production model:** `qwen/qwen3.6-27b` on Groq (llama-3.3-70b-versatile deprecated June 17 2026). Qwen 3.x thinking mode is disabled via `reasoning_effort: "none"` to prevent `<think>` tokens from breaking JSON parsing.
- RAG pre-filter (`query_similar_memes`) finds the 8 most relevant templates, merged with an 18-template core list (core templates listed first), capped at 25 — keeps the prompt under token limits.
- Response is parsed via `json.loads()` + `_normalize_llm_response()` (handles common LLM JSON format deviations) + Pydantic validation.
- Both the primary parse attempt and the retry each wrap the full `_call_llm()` + parse chain in `try/except (json.JSONDecodeError, ValidationError, ValueError, KeyError, httpx.HTTPError)` — this ensures `httpx.HTTPError` from network failures can't bypass the hard fallback.
- **`template_id` is validated against the known ChromaDB id set on both the primary and retry attempt** — if the LLM hallucinates an id not in the catalog, it's rejected and retried rather than passed to the compositor (which would 404).
- Hard fallback (`hide_the_pain_harold`) guarantees `parse_intent` never raises to the caller.
- `USE_WHEN` dict: each template_id maps to a terse description including NOT-FOR language naming specific alternatives — prevents common confusion clusters (drake/evil_kermit/two_buttons, distracted_boyfriend/left_exit_12/uno_draw_25_cards, etc.).

### Vision & Uploads (`nlp/vision.py`, `uploads/`) — Phase 0 + Phase 1 of multimodal input
- **Invariant: `uploads/safe_ingest.py`'s `safe_ingest()` is the only entry point for any uploaded image.** Pipeline in order: streamed size cap (10MB, doesn't trust `Content-Length`) → magic-byte type sniffing (hand-rolled signature dict, never trusts the extension or client-supplied MIME type — deliberately skips `python-magic` to avoid a new system `libmagic` dependency Render's native build has no precedent for) → Pillow decompression-bomb guard (`Image.MAX_IMAGE_PIXELS` + an explicit >8000px-per-side check) → metadata stripping (rebuilds a fresh `Image` via `Image.frombytes()`, guaranteeing an empty `.info` dict — no EXIF/GPS can survive) → content moderation.
- **Never writes the original upload to disk** — everything happens in memory. `uploads/retention.py` ships a TTL-tracked cleanup utility (`tracked_temp_file()`, `purge_expired()`, a periodic sweep started in `main.py`'s lifespan) as forward-looking infrastructure for Phase 3 (video), which will need a real file for ffmpeg; it's not exercised by anything today.
- **Moderation (`uploads/moderation.py`) deliberately does NOT use a dedicated Llama-Guard-style model.** Its exact request/response contract on Groq couldn't be live-verified (no `GROQ_API_KEY` available at implementation time), and shipping against an unverified contract risks silently failing *open*. Instead it reuses `nlp/vision.py`'s already-verified Groq vision call with a strict safety rubric — exactly the master prompt's documented fallback. Fails **closed** (rejects) on any provider error or missing config — an inability to moderate is treated as a failed moderation check, never a pass-through.
- **`nlp/vision.py`'s `describe_image()`** mirrors `intent_router.py`'s `_call_groq`/`_call_ollama` dispatch shape. Primary: Groq `qwen/qwen3.6-27b` — the *same model* `intent_router.py` already uses for text routing, so this needs zero new provider account. Optional fallback: Anthropic `claude-sonnet-5` via raw `httpx` (no SDK, matching this repo's existing style), gated on `ANTHROPIC_API_KEY` being set. Raises `VisionUnavailable` if both fail — unlike `parse_intent()`, there's no safe hardcoded fallback description, so the caller degrades to asking the user to describe the photo in words.
- **`POST /chat/image/`** (in `routers/chat.py`) is a sibling route to `POST /chat/`, not a retrofit of it — FastAPI routes bind to one body type, and this keeps the existing JSON `/chat/` contract provably unchanged. Both routes share a single extracted `_stream_chat_turn()` generator for the analyzing → `parse_intent` → rendering → `compose_meme` → `log_usage` → done sequence. **`parse_intent()` and `compositor.py` needed zero changes** — the vision-derived description is just a plain string fed into the same `parse_intent(user_message, ...)` call `/chat/` already makes.
- Rate-limited via `slowapi` (`backend/rate_limit.py` holds the shared `Limiter` instance in its own module specifically to avoid a `main.py` ↔ `routers/chat.py` circular import) — currently scoped to `/chat/image/` only, not yet applied to `/chat/`.
- Phase 2 (canvas mode — captioning the user's own photo) and Phase 3 (video) are not yet implemented; see `memegpt-multimodal-master-prompt.md` and the plan history for scope.

### Vector DB (`vector_db/chroma_client.py`)
- ChromaDB uses its default embedding model (`all-MiniLM-L6-v2`) — no external embedding API key required.
- Dual-mode client: `PersistentClient` for local dev / Render (embedded, no `CHROMA_HOST`), `HttpClient` when `CHROMA_HOST` is set (Docker Compose).
- `main.py` auto-seeds all templates found in `backend/templates/` on startup if the collection is empty — no manual seed step needed for a fresh deploy.
- Seeding is **sequential** (templates first, then few-shot examples via `examples_store.seed_examples()`). Concurrent ChromaDB embedding model loads spiked past Render's 512MB free-tier limit; serialized into `_sequential_seed()` run in a single background thread.
- `usage_count` and `recent_uses` are stored as metadata fields (not documents) so they survive re-embedding without touching the document text.
- Few-shot examples seeded into a separate ChromaDB collection by `examples_store.py` — 15 curated (prompt → template) pairs covering the most abstract/confusable templates, auto-seeded on startup via `seed_examples()`.
- **Known duplication:** `backend/data/curated_examples.jsonl` (51 older examples, popular templates) is a second, disconnected few-shot source seeded only by manually running `scripts/seed_examples.py`. It predates the 15-item hardcoded set and the two have no defined relationship — running the script adds to, rather than replaces, the auto-seeded set.

### Frontend (`frontend/`)
- `next.config.js` rewrites `/api/*` → `process.env.BACKEND_URL` (defaults to `localhost:8000`) so the frontend never hardcodes the backend URL in component code. `remotePatterns` allow image loading from `localhost`, the Docker `backend` hostname, and `*.onrender.com`.
- **`app/api/chat/route.ts` overrides the generic rewrite for `/chat/`** — Next.js checks the filesystem for a matching route before applying `rewrites()`, and `rewrites()` buffers the entire upstream response before forwarding, which breaks SSE. The route handler pipes the backend's `ReadableStream` straight through instead.
- Tailwind brand color palette uses shades 50–900 (all must be defined; missing shades like 400 cause Vercel build failures if referenced in CSS).
- `memeImageUrl()` in `lib/api.ts` prefixes relative meme URLs with `process.env.NEXT_PUBLIC_API_BASE` (must be set in Vercel for production; falls back to `localhost:8000` for local dev).
- Conversation state (`conversationId`) is held in `ChatWindow` component state — intentionally ephemeral, resets on page refresh.
- Backend-side conversation memory (`backend/memory/conversation_store.py`) tracks the last 5 template ids per `conversation_id` and feeds them to `parse_intent(..., avoid_templates=...)` so the LLM is nudged away from repeating the same template within a session.
- `/share` page + `ShareButtons.tsx` + `manifest.json` implement a basic PWA share flow (Web Share API with a copy-link fallback).
- `ChatWindow.tsx` has a hidden file input behind an attach button; `lib/api.ts`'s `sendChatImageStream()` posts a `FormData` (never sets `Content-Type` manually — the browser fills in the multipart boundary) to `/api/chat/image/` and shares the same SSE-consuming loop as `sendChatStream()`. The 10MB client-side size check here is a UX nicety only — `uploads/safe_ingest.py` is the real gate.

### Deployment
- **Backend (Render):** native Python runtime (`env: python` in `render.yaml`), not Docker — the service must be configured this way in Settings if created manually through the dashboard, since render.yaml service-type changes don't apply retroactively to manually-created services. Build command installs deps + downloads Anton font. `LLM_PROVIDER=groq` + `GROQ_API_KEY` env var for cloud inference (Render's CPU-only free tier can't run Ollama at usable speed). The same `GROQ_API_KEY` also powers Phase 1 vision + moderation calls — no new required env var for the multimodal feature to work; `ANTHROPIC_API_KEY` is optional (vision fallback only).
- **Frontend (Vercel):** needs `BACKEND_URL` (server-side rewrites) and `NEXT_PUBLIC_API_BASE` (client-side image URLs) pointed at the Render backend URL.
- Render free tier spins down after 15 min idle — first request after idle takes ~30s to wake up.

---

## Remaining Implementation Work

### Medium Priority
- [ ] **User-uploaded templates**: `POST /templates/upload` endpoint — accept an image, extract dominant color palette, generate a `template_id`, write to `backend/templates/`, upsert into ChromaDB.
- [x] **Conversation history**: `backend/memory/conversation_store.py` tracks recent template ids per conversation and passes them to `parse_intent` as `avoid_templates` to reduce repetition. (Full prior-message context, not just template ids, is still not passed back.)
- [ ] **Fine-tuned model**: scripts for LoRA fine-tuning on the Imgflip 100k dataset exist (`scripts/finetune_unsloth.py`) but training hasn't been run.

### Low Priority / Polish
- [x] **Rate limiting** (`slowapi`): implemented, but currently scoped only to `/chat/image/` (the upload path). Extending it to plain-text `/chat/` is still pending.
- [x] **Tests**: `backend/tests/` now exists (first test suite in the repo) — Phase 0 upload safety-gate tests and a `/chat/` text-flow regression test via `httpx.AsyncClient`. Still missing: `compositor.py` golden-image-diff tests and `intent_router.py` Groq/Ollama mock tests.
- [ ] **Multimodal Phase 2/3**: canvas mode (caption the user's own photo) and video support — see `memegpt-multimodal-master-prompt.md`.
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
