# MemeGPT — System Documentation

## Overview

MemeGPT is a chatbot that communicates exclusively through memes. A user sends a plain-English message; the system routes it through an LLM intent-parsing layer (Ollama locally, Groq in production), does a RAG pre-filter over 100 templates via ChromaDB, picks the best meme template, renders caption text onto the image using Pillow, and streams the result back to a React/Next.js chat interface via SSE.

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
│   │   ├── chat.py           POST /chat/     — main conversational endpoint, SSE stream
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
│   │   └── intent_router.py  _call_llm() dispatches to Ollama (local) or Groq (cloud) → IntentResponse JSON
│   │
│   ├── templates/            100 base meme images (JPG/PNG), named by template_id
│   ├── fonts/                Anton-Regular.ttf (downloaded at build time — free Impact equivalent)
│   ├── static/generated/     Runtime output — compositor writes PNGs here (ephemeral on Render)
│   └── data/chroma/          ChromaDB persistent store (git-ignored)
│
├── frontend/                 Next.js 14 + Tailwind CSS (TypeScript)
│   └── src/
│       ├── app/
│       │   ├── layout.tsx    Root layout, dark theme, Inter font
│       │   ├── page.tsx      Single-page entry — renders <ChatWindow />
│       │   └── globals.css   Tailwind directives + scrollbar + fadeIn animation
│       ├── components/
│       │   ├── ChatWindow.tsx  Stateful chat container, SSE consumer, conversation ID
│       │   ├── MessageBubble.tsx  Per-message bubble (user right, bot left) + feedback buttons
│       │   └── MemeDisplay.tsx   next/image wrapper for rendered memes
│       ├── lib/
│       │   └── api.ts         Typed fetch helpers: sendChatStream, generateMeme, explainMeme, memeImageUrl
│       └── types/
│           └── index.ts       Shared TypeScript interfaces mirroring backend schemas
│
├── render.yaml                Render.com Blueprint — native Python env, build/start commands
└── scripts/
    ├── seed_templates.py       Manual seed CLI (auto-seed on startup makes this optional now)
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
- RAG pre-filter (`query_similar_memes`) finds the 8 most relevant templates, merged with a core list, capped at 20 — keeps the prompt under Ollama's 4096-token context.
- Response is parsed via `json.loads()` + `_normalize_llm_response()` (handles common LLM JSON format deviations) + Pydantic validation.
- **`template_id` is validated against the known ChromaDB id set on both the primary and retry attempt** — if the LLM hallucinates an id not in the catalog, it's rejected and retried rather than passed to the compositor (which would 404).
- Hard fallback (`hide_the_pain_harold`) guarantees `parse_intent` never raises to the caller.

### Vector DB (`vector_db/chroma_client.py`)
- ChromaDB uses its default embedding model (`all-MiniLM-L6-v2`) — no external embedding API key required.
- Dual-mode client: `PersistentClient` for local dev / Render (embedded, no `CHROMA_HOST`), `HttpClient` when `CHROMA_HOST` is set (Docker Compose).
- `main.py` auto-seeds all templates found in `backend/templates/` on startup if the collection is empty — no manual seed step needed for a fresh deploy.
- `usage_count` and `recent_uses` are stored as metadata fields (not documents) so they survive re-embedding without touching the document text.

### Frontend (`frontend/`)
- `next.config.js` rewrites `/api/*` → `process.env.BACKEND_URL` (defaults to `localhost:8000`) so the frontend never hardcodes the backend URL in component code. `remotePatterns` allow image loading from `localhost`, the Docker `backend` hostname, and `*.onrender.com`.
- `memeImageUrl()` in `lib/api.ts` prefixes relative meme URLs with `process.env.NEXT_PUBLIC_API_BASE` (must be set in Vercel for production; falls back to `localhost:8000` for local dev).
- Conversation state (`conversationId`) is held in `ChatWindow` component state — intentionally ephemeral, resets on page refresh.

### Deployment
- **Backend (Render):** native Python runtime (`env: python` in `render.yaml`), not Docker — the service must be configured this way in Settings if created manually through the dashboard, since render.yaml service-type changes don't apply retroactively to manually-created services. Build command installs deps + downloads Anton font. `LLM_PROVIDER=groq` + `GROQ_API_KEY` env var for cloud inference (Render's CPU-only free tier can't run Ollama at usable speed).
- **Frontend (Vercel):** needs `BACKEND_URL` (server-side rewrites) and `NEXT_PUBLIC_API_BASE` (client-side image URLs) pointed at the Render backend URL.
- Render free tier spins down after 15 min idle — first request after idle takes ~30s to wake up.

---

## Remaining Implementation Work

### Medium Priority
- [ ] **Multi-panel templates beyond current set**: `TextBoxConfig` already supports arbitrary coordinates for any new template — just add an entry to `TEMPLATE_CATALOG`.
- [ ] **User-uploaded templates**: `POST /templates/upload` endpoint — accept an image, extract dominant color palette, generate a `template_id`, write to `backend/templates/`, upsert into ChromaDB.
- [ ] **Conversation history**: pass prior `ChatMessage` turns back to the LLM as context so it can build on previous memes in a session.
- [ ] **Fine-tuned model**: scripts for LoRA fine-tuning on the Imgflip 100k dataset exist (`scripts/finetune_unsloth.py`) but training hasn't been run.

### Low Priority / Polish
- [ ] **Rate limiting** (`slowapi`): guard `/chat/` against spam, especially since the deployed instance is publicly shared.
- [ ] **Tests**: pytest suite for `compositor.py` (golden-image diff), `intent_router.py` (mock Ollama/Groq), and router integration tests using `httpx.AsyncClient`.
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
