<div align="center">

# MemeGPT

### An AI chatbot that only talks in memes — LLM intent routing, RAG template retrieval, multimodal vision, and real-time image composition.

[![Live Demo](https://img.shields.io/badge/Live_Demo-memegpt--six.vercel.app-7C3AED?style=flat-square)](https://memegpt-six.vercel.app)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Postgres](https://img.shields.io/badge/Postgres-Supabase-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com)
[![Groq](https://img.shields.io/badge/Groq-Cloud_LLM-F55036?style=flat-square)](https://groq.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-FF6B35?style=flat-square)](https://www.trychroma.com/)
[![Cloudflare R2](https://img.shields.io/badge/Cloudflare-R2%20%2B%20Workers-F38020?style=flat-square&logo=cloudflare&logoColor=white)](https://developers.cloudflare.com/r2/)
[![Discord](https://img.shields.io/badge/Discord-%2Fmeme-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-gray?style=flat-square)](LICENSE)

</div>

---

MemeGPT is a chatbot that communicates exclusively through memes. Type a message (or paste a whole group-chat dump, or upload a photo), and it routes through an LLM intent-parsing layer, does a RAG pre-filter over 120+ meme templates, picks the best match (or, for a photo, captions it directly), renders text onto the image with a pixel-accurate Pillow compositor, and streams the result back in real time.

**[Try it live →](https://memegpt-six.vercel.app)**

The product has four real surfaces, plus a marketing front door:

- **`/`** — a public landing page explaining the product and linking into the four surfaces below. Not the app itself.
- **`/chat`** — a normal chatbot. The catch: it only replies in memes.
- **`/lore`** — for big context dumps. Paste a whole group chat, upload a stack of screenshots, get several memes back — with explicit controls (meme count, drag-and-drop) that Chat deliberately doesn't expose.
- **`/make`** — skips the AI's judgment entirely: search the full template library and write your own captions box by box. A separate, simpler direct template+caption→image path with no LLM/RAG involved — captions still pass through a content-moderation gate before rendering, since they never get the implicit judgment call an LLM gives the other surfaces' captions.
- **`/arc`** — a roast-flavored personal recap (aura score, streaks, top template) scored across usage from all three surfaces above.

Optional accounts (email or Google, via Supabase Auth) unlock a persisted chat-history sidebar and cross-device memory. Everything also works fully anonymously — no signup required, ever.

Two LLM backends, swappable via `LLM_PROVIDER`: **Ollama** (local, zero cost, no API key) for development, or **Groq** (free-tier cloud inference) for production, with an automatic secondary-model fallback and a circuit breaker for resilience during rate-limit windows.

---

## Demo

| Input | What happens |
|---|---|
| `"when the intern pushes directly to main"` | Matches Gru's Plan (4-panel) via RAG + LLM template selection |
| A photo + `"make this a meme"` | Canvas mode — the photo becomes the meme directly, captioned top/bottom |
| A long pasted group-chat thread | Segmented into 2-5 distinct meme-worthy moments, each rendered separately |
| 👍 on a generated meme | Feeds a per-user humor profile that nudges future template picks |
| `/meme <text>` in Discord | Same generation pipeline, delivered as a slash command reply |
| Picking a template + typing captions in Make | Renders directly, no LLM/RAG involved — just a content-safety check first |

---

## Architecture

```
Text and/or photos (Chat, Lore, or Discord /meme)
      │
      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  POST /chat/ or /lore/  (FastAPI, SSE streaming)                     │
│                                                                       │
│  uploads/safe_ingest.py    every photo: size cap, magic-byte type    │
│                              check, decompression-bomb guard, EXIF   │
│                              strip, content moderation               │
│                                                                       │
│  nlp/vision.py             Mode 1 (context): describe the photo(s)   │
│                              Mode 2 (canvas): caption the photo       │
│                              directly, no template lookup             │
│                                                                       │
│  nlp/segmentation.py       splits one submission into 1..N distinct  │
│                              meme-worthy situations                   │
│                                                                       │
│  ┌── per situation, sequentially ─────────────────────────────────┐ │
│  │  vector_db/chroma_client.py   RAG: 8 semantically similar       │ │
│  │                                 templates via ChromaDB           │ │
│  │  nlp/intent_router.py         Groq / Ollama → structured JSON   │ │
│  │                                 (template_id, captions) with a  │ │
│  │                                 retry + secondary-model fallback│ │
│  │  image_processing/compositor.py  Pillow: per-template text      │ │
│  │                                 boxes, stroke, watermark         │ │
│  │  storage/ + db/                R2 (or local disk) + Postgres    │ │
│  │                                 as source of truth               │ │
│  └───────────────────────────────────────────────────────────────┘ │
└───────────────────────────────┬───────────────────────────────────┘
                                 │  SSE: thinking → plan → done × N → batch_done
                                 ▼
                 Next.js 14 UI — Chat carousel / Lore feed
                 real-time, progressive, one meme at a time
```

Make (`/generate/`) deliberately bypasses all of the above — no LLM, no RAG, no segmentation. A user picks a `template_id` and types captions directly; the only gate before `compositor.py` is a text content-moderation check, since Make's captions never get an LLM's implicit judgment call the way Chat/Lore's do.

---

## Features

**Core generation**
- **LLM intent routing** — a structured-JSON call (Groq in production, Ollama locally) picks a template and writes captions, validated against the real template catalog before ever touching the compositor. Retries on hallucinated ids or malformed JSON; a secondary-model fallback and a per-model circuit breaker keep generation working through Groq rate-limit windows.
- **RAG template retrieval** — ChromaDB semantic search over 120+ templates, precomputed embeddings checked into the repo so a cold start never re-pays the embedding cost.
- **Multi-context, multi-meme generation** — a long dump or several photos gets segmented into distinct meme-worthy moments and rendered as separate memes in one streamed batch, not flattened into one.
- **Multimodal input** — upload photos in either Mode 1 (context: described, then matched to a catalog template) or Mode 2 (canvas: the photo becomes the meme itself, captioned directly). Every upload passes through one hardened ingestion gate: size cap, magic-byte type sniffing, decompression-bomb guard, metadata stripping, and content moderation.
- **Pixel-accurate compositor** — Pillow-based, per-template bounding boxes, auto-shrinking text, 8-directional stroke, animated GIF templates (frame-by-frame captioning), a brand watermark, and a PNG provenance tag on every render.

**Product surfaces**
- **Chat vs Lore** — one backend, two purpose-built frontends: Chat is minimal-chrome auto-everything; Lore exposes meme-count and drag-and-drop for big context dumps, plus an opt-in "remember lore" lexicon for recurring names/running jokes.
- **Make** — the manual meme-maker: search the full 120+ template catalog and write your own captions box by box, no AI in the loop at all. Bypasses the whole intent-routing/RAG/segmentation pipeline; captions go through a Groq-based content-moderation gate (same fail-closed contract as the image pipeline) since they're the one place typed text lands on a public meme with no LLM's implicit judgment.
- **Arc** — a roast-flavored personal recap ("aura" score, tiers, template roasts) scored across usage from Chat, Lore, and Make, rendered as a shareable card and a Stories-style tap-through reveal.
- **Optional accounts** — email or Google sign-in via Supabase Auth links your anonymous history to a real account, unlocking a persisted chat-history sidebar with per-chat delete. Fully anonymous use (localStorage UUID, no signup) still works identically for anyone who skips sign-in.
- **Discord `/meme`** — a Cloudflare Worker handles Discord's ed25519 handshake and forwards to the same generation pipeline.
- **Share pages** — every generated meme gets a durable `/m/{id}` page with Open Graph tags, backed by R2 storage and Postgres (survives redeploys — Render's disk doesn't).

**Personalization & memory**
- No-signup anonymous memory: cross-session avoid-repeat template tracking, a feedback-derived humor profile, an opt-in lexicon for callback humor — all keyed off a `localStorage` UUID, no account needed.
- A one-click "Forget me" erases everything tied to that identity; signed-in users get the same guarantee per-chat.

**Reliability & ops**
- Every LLM call site is bounded, retried, and has a safe hard fallback — `parse_intent()` never raises to the caller.
- A weekly trend-discovery pipeline scans Imgflip for new templates, dedupes via perceptual hashing, drafts catalog entries with a vision model, and opens a human-reviewed PR — never auto-merges.
- A `MAINTENANCE_MODE` flag swaps the entire site to a self-contained coming-soon page via middleware, no redeploy of app code required.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI + Uvicorn, SSE streaming |
| LLM inference | Groq (production) / Ollama (local dev) — swappable via `LLM_PROVIDER` |
| Vision | Groq vision (primary), Anthropic (fallback) |
| Vector store / RAG | ChromaDB, Gemini embeddings in production (local model in dev) |
| Relational store | Postgres (Supabase), raw `asyncpg`, no ORM |
| Object storage | Cloudflare R2 (S3-compatible), local disk fallback |
| Auth | Supabase Auth (email + Google), verified server-side per request |
| Image processing | Pillow — per-template layouts, stroke text, GIF frame compositing |
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind CSS |
| Bot integration | Cloudflare Worker (TypeScript) for Discord's `/meme` slash command |
| CI | GitHub Actions — weekly trend-discovery pipeline |
| Deployment | Render (backend), Vercel (frontend) |

---

## Project Structure

```
memegpt/
├── backend/                       FastAPI application (Python 3.11+)
│   ├── main.py                    Entry point — routers, CORS, static mounts, auto-seed
│   ├── routers/                   chat, lore, arc, explain, generate, feedback, memes,
│   │                               me, auth, conversations, discord, share_intake
│   ├── nlp/                       llm_client, intent_router, segmentation, vision, lexicon
│   ├── uploads/                   safe_ingest — the one entry point for any uploaded image
│   ├── image_processing/          compositor.py + per-template layout configs
│   ├── vector_db/                 ChromaDB client + few-shot example store
│   ├── db/                        Postgres pool + schema + all read/write functions
│   ├── storage/                   R2 / local-disk meme storage
│   ├── auth.py, identity.py       Supabase-verified users + anonymous identity
│   ├── arc/                       aura scoring + roast copy
│   ├── memory/                    in-memory per-conversation template history
│   ├── scripts/                   eval harnesses, trend pipeline, embedding precompute
│   ├── templates/                 120+ meme images (static + animated GIF)
│   └── tests/                     pytest suite
│
├── frontend/                      Next.js 14 + Tailwind (TypeScript)
│   └── src/
│       ├── app/                   /, /chat, /lore, /arc, /m/[id], /auth, share-target
│       ├── components/            ModeTabs, ChatWindow, LoreView, ArcView,
│       │                           ConversationSidebar, AuthControl, LandingPage
│       ├── hooks/                 useMemeStream (shared SSE logic, Chat + Lore)
│       └── lib/                   api.ts, identity.ts, supabaseClient.ts
│
├── integrations/discord-worker/   Cloudflare Worker fronting Discord's /meme command
├── .github/workflows/             weekly trend-discovery pipeline
├── docs/                          uploads, fine-tune runbook, Discord setup
├── scripts/                       template/example seeding, fine-tune data prep
├── docker-compose.yml             Ollama + ChromaDB + backend + frontend, self-hosted
└── render.yaml                    Render Blueprint
```

---

## Quick Start

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
# → http://localhost:8000  (Swagger UI at /docs)
# Templates auto-seed into ChromaDB on first startup if empty.
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

Postgres (`DATABASE_URL`), R2 (`R2_*`), and Supabase Auth (`SUPABASE_URL` + friends) are all optional and feature-flagged — unset means local-disk storage, no durable persistence, and anonymous-only use. Nothing crashes without them; see `backend/.env.example`.

### Docker Compose (full self-hosted stack)

```bash
git clone https://github.com/Moulik04/memegpt.git && cd memegpt
cp .env.example .env
ollama pull llama3.1:8b && ollama serve   # native, for Metal/CUDA access
docker compose up -d --build
docker exec memegpt-backend python scripts/seed_templates.py   # first run only
```

### Verify the compositor (no services needed)

```bash
pip install Pillow
python scripts/dummy_template_test.py
# → scripts/dummy_output.png
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat/`, `/chat/image/` | Chat surface — SSE stream, text and/or photos |
| `POST` | `/lore/`, `/lore/image/` | Lore surface — same core, adds `meme_count` + lexicon opt-in |
| `GET` | `/arc`, `POST /arc/card` | Personal meme stats + shareable recap card |
| `GET`/`POST` | `/explain/` | Every template's metadata, or one template's + usage history — Make's picker |
| `POST` | `/generate/` | Make — render `template_id` + `texts` directly, no LLM/RAG (moderation-gated) |
| `POST` | `/feedback/` | Thumbs up / down on a generated meme |
| `GET` | `/memes/{id}` | Durable share-page lookup (`/m/{id}` on the frontend) |
| `GET` | `/auth/whoami` | Verified identity for the current bearer token |
| `POST` | `/auth/link-anon` | Link anonymous history to a signed-in account |
| `GET/POST/PATCH/DELETE` | `/conversations` | Persisted chat history (signed-in only) |
| `DELETE` | `/me` | Forget-me — erases all data tied to an identity |
| `POST` | `/discord/generate` | Discord `/meme` slash-command backend |
| `POST` | `/share-intake/` | PWA share-target stash/retrieve |
| `GET` | `/health` | Liveness check |

### `POST /chat/` — SSE stream

```
data: {"type": "thinking", "stage": "analyzing", "message": "Reading your vibe..."}
data: {"type": "thinking", "stage": "rendering", "template_id": "drake"}
data: {"type": "done", "conversation_id": "…", "message": {"meme_url": "...", "meme_id": "..."}, "template_used": "drake"}
data: {"type": "batch_done", "total": 1, "succeeded": 1}
```

---

## Roadmap

All seven phases of the original growth plan (A–G) are shipped, plus an appended Phase H:

- [x] **A** — Watermark + PNG provenance tag on every generated meme
- [x] **B** — Durable storage (R2 + Postgres) and `/m/{id}` share pages with Open Graph tags
- [x] **C** — Anonymous identity + memory (cross-session avoid-repeat, humor profile, opt-in lexicon, Forget-me)
- [x] **D** — Arc: aura-scored, roast-flavored personal recap with a from-scratch share card
- [x] **E** — Weekly trend-discovery pipeline (Imgflip scan → perceptual-hash dedup → vision-drafted PR)
- [x] **F** — Fine-tune preparation (Imgflip 100k → ChatML pipeline verified, Colab runbook written; the actual training run is a deliberately separate, manual GPU step)
- [x] **G** — Animated GIF templates + a Discord `/meme` slash command via Cloudflare Worker
- [x] **H** — Optional accounts (email + Google), linked anonymous history, persisted chat sidebar, per-chat delete

**Not yet started:**
- [ ] Multimodal Phase 3 — video input (ffmpeg availability confirmed on Render; time-budget architecture not yet decided)
- [ ] User-uploaded custom templates (`POST /templates/upload`)
- [ ] Fine-tuned model actually trained and swapped into production
- [ ] `compositor.py` golden-image-diff test coverage

---

## License

MIT — see [LICENSE](LICENSE).
