# MemeGPT — System Documentation

## Overview

MemeGPT is a chatbot that communicates exclusively through memes. A user sends a plain-English message; the system routes it through an LLM intent-parsing layer, picks the best meme template, renders caption text onto the image using Pillow, and streams the result back to a React/Next.js chat interface.

---

## Repository Layout

```
memegpt/
├── backend/                  FastAPI application (Python 3.11+)
│   ├── main.py               Entry point — mounts routers, CORS, static files, lifespan
│   ├── schemas.py            Pydantic v2 models shared across all layers
│   ├── pyproject.toml        All Python dependencies + dev tooling config
│   │
│   ├── routers/
│   │   ├── chat.py           POST /chat/     — main conversational endpoint
│   │   ├── explain.py        POST /explain/  — template metadata & history
│   │   └── generate.py       POST /generate/ — on-demand meme generation
│   │
│   ├── image_processing/
│   │   └── compositor.py     Pillow text compositor (font loading, wrap, stroke)
│   │
│   ├── vector_db/
│   │   └── chroma_client.py  ChromaDB singleton — upsert, query, log_usage
│   │
│   ├── nlp/
│   │   └── intent_router.py  Claude API call → structured IntentResponse JSON
│   │
│   ├── templates/            Base meme images (JPG/PNG). Add files here.
│   ├── fonts/                Drop Impact.ttf or Arial.ttf here (not committed).
│   ├── static/generated/     Runtime output — compositor writes PNGs here.
│   └── data/chroma/          ChromaDB persistent store (git-ignored).
│
├── frontend/                 Next.js 14 + Tailwind CSS (TypeScript)
│   └── src/
│       ├── app/
│       │   ├── layout.tsx    Root layout, dark theme, Inter font
│       │   ├── page.tsx      Single-page entry — renders <ChatWindow />
│       │   └── globals.css   Tailwind directives + scrollbar + fadeIn animation
│       ├── components/
│       │   ├── ChatWindow.tsx  Stateful chat container, send logic, conversation ID
│       │   ├── MessageBubble.tsx  Per-message bubble (user right, bot left)
│       │   └── MemeDisplay.tsx   next/image wrapper for rendered memes
│       ├── lib/
│       │   └── api.ts         Typed fetch helpers: sendChat, generateMeme, explainMeme
│       └── types/
│           └── index.ts       Shared TypeScript interfaces mirroring backend schemas
│
└── scripts/
    └── dummy_template_test.py  Standalone Pillow PoC — run without any backend services
```

---

## Data Flow (per chat turn)

```
User types message
      │
      ▼
POST /chat/  (routers/chat.py)
      │
      ├─► nlp/intent_router.py
      │     └─ Claude API (claude-sonnet-4-6, JSON mode)
      │         └─ Returns: { template_id, top_text, bottom_text, reasoning }
      │
      ├─► vector_db/chroma_client.query_similar_memes()
      │     └─ Semantic search for contextually similar past memes (informational)
      │
      ├─► image_processing/compositor.compose_meme()
      │     └─ Pillow: open template → wrap text → draw stroke → save PNG
      │         └─ Returns: "/static/generated/<id>.png"
      │
      └─► vector_db/chroma_client.log_usage()
            └─ Appends usage event to template's ChromaDB metadata

Response: { conversation_id, message: { role, content, meme_url }, template_used }
      │
      ▼
Frontend fetches meme_url from http://localhost:8000/static/generated/<id>.png
<MemeDisplay /> renders the image with next/image
```

---

## Key Design Decisions

### Schemas (`schemas.py`)
- `TextBox` defines a bounding box in **pixel coordinates** relative to the template image. This allows templates to have arbitrary layouts (multi-panel, side-by-side) — not just top/bottom.
- `MemeTemplate.history` is a lightweight append-only list stored in ChromaDB metadata for now. Move to PostgreSQL once history grows beyond a few hundred entries per template.

### Image Compositor (`image_processing/compositor.py`)
- Font resolution order: `backend/fonts/` → system paths (macOS → Linux) → Pillow built-in fallback.
- Text wrapping uses `textwrap.wrap()` with a char-count estimate from `font.getlength("A")`. This is an approximation — proportional fonts vary. A more accurate approach is binary-search on `font.getlength(line)` against `box.width`.
- Stroke is drawn as an 8-directional offset pass before the fill pass — classic meme rendering.
- Output is always PNG (lossless, supports transparency) regardless of input format.

### NLP / Intent Router (`nlp/intent_router.py`)
- Uses `claude-sonnet-4-6` with a strict system prompt listing known template IDs.
- Response is parsed via `json.loads()` + Pydantic validation — no regex heuristics.
- If the LLM hallucinates an unknown `template_id`, the compositor will raise `FileNotFoundError` (caught in `chat.py` → 404). Future: validate `template_id` against ChromaDB before calling the compositor.

### Vector DB (`vector_db/chroma_client.py`)
- ChromaDB uses its default embedding model (`all-MiniLM-L6-v2`) — no external embedding API key required.
- Templates must be seeded via `upsert_template()` before they can surface in semantic search. Add a `scripts/seed_templates.py` to do this at startup.
- `usage_count` and `recent_uses` are stored as metadata fields (not documents) so they survive re-embedding without touching the document text.

### Frontend (`frontend/`)
- `next.config.js` rewrites `/api/*` → `http://localhost:8000/*` so the frontend never hardcodes the backend URL in component code.
- `memeImageUrl()` in `lib/api.ts` handles the `localhost:8000` prefix for images; swap to an env var (`NEXT_PUBLIC_API_BASE`) for production.
- Conversation state (`conversationId`) is held in `ChatWindow` component state — intentionally ephemeral. Add `localStorage` persistence or a `/conversations` API if you need session replay.

---

## Remaining Implementation Work

### High Priority
- [ ] **Seed script** (`scripts/seed_templates.py`): call `upsert_template()` for each template image in `backend/templates/`. Should run at server startup or as a one-shot CLI.
- [ ] **Add real template images**: drop `.jpg`/`.png` files into `backend/templates/` named by their `template_id` (e.g. `drake.jpg`, `distracted_boyfriend.jpg`).
- [ ] **Environment config** (`backend/.env`): `ANTHROPIC_API_KEY` must be set. Add `pydantic-settings` `Settings` class in `backend/config.py` loaded at startup.
- [ ] **`/explain` deeper integration**: surface `recent_uses` in the frontend as a "Why this meme?" tooltip on assistant bubbles.

### Medium Priority
- [ ] **Multi-panel templates**: `TextBox` already supports arbitrary coordinates. Wire the compositor to accept a list of `TextBox` objects from the stored `MemeTemplate` schema instead of always using the hardcoded top/bottom zones.
- [ ] **User-uploaded templates**: `POST /templates/upload` endpoint — accept an image, extract dominant color palette, generate a `template_id`, write to `backend/templates/`, upsert into ChromaDB.
- [ ] **Streaming responses**: convert `POST /chat/` to use SSE (Server-Sent Events) so the frontend can show partial reasoning text before the image is ready.
- [ ] **Conversation history**: pass prior `ChatMessage` turns back to the LLM as context so it can build on previous memes in a session.

### Low Priority / Polish
- [ ] **Rate limiting** (`slowapi`): guard `/chat/` against spam.
- [ ] **Tests**: pytest suite for `compositor.py` (golden-image diff), `intent_router.py` (mock Anthropic), and router integration tests using `httpx.AsyncClient`.
- [ ] **Docker Compose**: `backend` + `frontend` services with a shared volume for `static/generated/`.
- [ ] **Production image URL**: replace `localhost:8000` with `NEXT_PUBLIC_API_BASE` env var and add a CDN upload step in the compositor.

---

## Local Development Quickstart

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-...
uvicorn main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
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
