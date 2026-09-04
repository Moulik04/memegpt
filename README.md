<div align="center">

# MemeGPT

### A chatbot that only replies in memes

[![Live Demo](https://img.shields.io/badge/Live_Demo-memegpt.app-7C3AED?style=flat-square)](https://memegpt.app)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Postgres](https://img.shields.io/badge/Postgres-Supabase-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com)
[![Groq](https://img.shields.io/badge/Groq-Cloud_LLM-F55036?style=flat-square)](https://groq.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-FF6B35?style=flat-square)](https://www.trychroma.com/)
[![Google Cloud](https://img.shields.io/badge/Google_Cloud-Cloud_Run-4285F4?style=flat-square&logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![Terraform](https://img.shields.io/badge/Terraform-IaC-7B42BC?style=flat-square&logo=terraform&logoColor=white)](https://www.terraform.io/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-GKE-326CE5?style=flat-square&logo=kubernetes&logoColor=white)](https://cloud.google.com/kubernetes-engine)
[![License: MIT](https://img.shields.io/badge/License-MIT-gray?style=flat-square)](LICENSE)

</div>

---

MemeGPT communicates exclusively through memes. Type a message, paste a whole group chat, or upload a photo. It routes through an LLM intent-parsing layer, does a RAG pre-filter over 120+ meme templates, picks the best match (or captions a photo directly), renders text onto the image with a pixel-accurate Pillow compositor, and streams the result back in real time.

**[Try it live](https://memegpt.app)**

The product has four real surfaces, plus a marketing front door:

- **`/`**: a public landing page that explains the product and links to the four surfaces below. Not the app itself.
- **`/chat`**: a normal chatbot. The catch is it only replies in memes.
- **`/lore`**: for big context dumps. Paste a whole group chat, upload a stack of screenshots, get several memes back. It exposes controls (meme count, drag and drop) that Chat deliberately doesn't.
- **`/make`**: skips the AI's judgment entirely. Search the full template library and write your own captions box by box. This is a separate, simpler path with no LLM or RAG involved, though captions still pass through a content-moderation gate before rendering.
- **`/arc`**: a roast-flavored personal recap (aura score, streaks, top template) scored across usage from all three surfaces above.

Optional accounts (email or Google, through Supabase Auth) unlock a persisted chat-history sidebar and cross-device memory. Everything also works fully anonymously, no signup required, ever.

Two LLM backends, swappable through `LLM_PROVIDER`: Ollama runs locally at zero cost for development, and Groq's free-tier cloud inference handles production, with an automatic secondary-model fallback and a circuit breaker to stay resilient during rate-limit windows.

---

## Demo

| Input | What happens |
|---|---|
| `"when the intern pushes directly to main"` | Matches Gru's Plan (4-panel) through RAG and LLM template selection |
| A photo plus `"make this a meme"` | Canvas mode. The photo becomes the meme directly, captioned top and bottom |
| A long pasted group-chat thread | Segmented into a handful of distinct meme-worthy moments, each rendered separately |
| A thumbs-up on a generated meme | Feeds a per-user humor profile that nudges future template picks |
| `/meme <text>` in Discord | Same generation pipeline, delivered as a slash command reply |
| Picking a template and typing captions in Make | Renders directly, no LLM or RAG involved, just a content-safety check first |

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
│  nlp/segmentation.py       splits one submission into several        │
│                              distinct meme-worthy situations          │
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
                 Next.js 14 UI, Chat carousel / Lore feed
                 real time, progressive, one meme at a time
```

Make (`/generate/`) skips all of the above on purpose. No LLM, no RAG, no segmentation. A user picks a `template_id` and types captions directly. The only gate before `compositor.py` is a text content-moderation check, since Make's captions never get an LLM's implicit judgment call the way Chat and Lore's do.

---

## Features

### Core generation

LLM intent routing picks a template and writes captions through a structured JSON call (Groq in production, Ollama locally), validated against the real template catalog before it ever touches the compositor. It retries on hallucinated ids or malformed JSON, and a secondary-model fallback plus a per-model circuit breaker keep generation working through Groq rate-limit windows.

RAG template retrieval runs ChromaDB semantic search over 120+ templates. Embeddings are precomputed and checked into the repo, so a cold start never re-pays the embedding cost.

A long dump or several photos gets segmented into distinct meme-worthy moments and rendered as separate memes in one streamed batch, instead of getting flattened into one.

Photo uploads work in either Mode 1 (context: described, then matched to a catalog template) or Mode 2 (canvas: the photo becomes the meme itself, captioned directly). Every upload passes through one hardened ingestion gate: size cap, magic-byte type sniffing, a decompression-bomb guard, metadata stripping, and content moderation.

The compositor is Pillow based, with per-template bounding boxes, auto-shrinking text, 8-directional stroke, animated GIF templates rendered frame by frame, a brand watermark, and a PNG provenance tag on every render.

### Product surfaces

Chat and Lore share one backend behind two purpose-built frontends. Chat is minimal-chrome and auto-everything. Lore exposes meme count and drag and drop for big context dumps, plus an opt-in "remember lore" lexicon for recurring names and running jokes.

Make is the manual meme-maker: search the full 120+ template catalog and write your own captions box by box, no AI in the loop at all. It bypasses the whole intent-routing, RAG, and segmentation pipeline. Captions go through a Groq-based content-moderation gate (the same fail-closed contract as the image pipeline), since they're the one place typed text lands on a public meme without an LLM's implicit judgment.

Arc is a roast-flavored personal recap (an aura score, tiers, template roasts) scored across usage from Chat, Lore, and Make, rendered as a shareable card and a Stories-style tap-through reveal.

Optional accounts let email or Google sign-in (through Supabase Auth) link your anonymous history to a real account, unlocking a persisted chat-history sidebar with per-chat delete. Fully anonymous use, a localStorage UUID with no signup, still works identically for anyone who skips sign-in.

A Cloudflare Worker handles Discord's ed25519 handshake for the `/meme` slash command and forwards it to the same generation pipeline.

Every generated meme gets a durable `/m/{id}` share page with Open Graph tags, backed by R2 storage and Postgres so it survives redeploys.

A real `/privacy` page, written in plain language rather than legal boilerplate, explains what the app stores and what it doesn't.

### Personalization and memory

No-signup anonymous memory covers cross-session avoid-repeat template tracking, a feedback-derived humor profile, and an opt-in lexicon for callback humor, all keyed off a `localStorage` UUID with no account needed.

A one-click "Forget me" erases everything tied to that identity. Signed-in users get the same guarantee per chat.

### Reliability and ops

Every LLM call site is bounded, retried, and has a safe hard fallback: `parse_intent()` never raises to the caller.

A weekly trend-discovery pipeline scans Imgflip for new templates, dedupes them with perceptual hashing, drafts catalog entries with a vision model, and opens a human-reviewed pull request. It never auto-merges.

A `MAINTENANCE_MODE` flag swaps the entire site to a self-contained coming-soon page through middleware, with no redeploy of app code required.

---

## Tech stack

| Layer | Technology |
|---|---|
| API framework | FastAPI + Uvicorn, SSE streaming |
| LLM inference | Groq in production, Ollama for local dev, swappable through `LLM_PROVIDER` |
| Vision | Groq vision as primary, Anthropic as fallback |
| Vector store / RAG | ChromaDB, Gemini embeddings in production, a local model in dev |
| Relational store | Postgres on Supabase, raw `asyncpg`, no ORM |
| Object storage | Cloudflare R2 (S3 compatible), with a local-disk fallback |
| Auth | Supabase Auth (email + Google), verified server-side on every request |
| Image processing | Pillow, with per-template layouts, stroke text, and GIF frame compositing |
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| Bot integration | A Cloudflare Worker (TypeScript) for Discord's `/meme` slash command |
| Cloud infrastructure | Google Cloud Run, provisioned entirely with Terraform |
| CI/CD | GitHub Actions: lint and test on every PR, an untrafficked candidate deploy smoke-tested before promotion on every merge, plus the weekly trend-discovery pipeline |
| Observability | OpenTelemetry metrics and structured logs shipped to Grafana Cloud, with SLO alerts |
| Kubernetes | A real GKE Autopilot cluster, Terraform-provisioned and verified against live public traffic (see [Infrastructure](#infrastructure)) |
| Deployment | Render (backend, currently live) and Vercel (frontend) |

---

## Project structure

```
memegpt/
├── backend/                       FastAPI application (Python 3.11+)
│   ├── main.py                    Entry point: routers, CORS, static mounts, auto-seed
│   ├── routers/                   chat, lore, arc, explain, generate, feedback, memes,
│   │                               me, auth, conversations, discord, share_intake
│   ├── nlp/                       llm_client, intent_router, segmentation, vision, lexicon
│   ├── uploads/                   safe_ingest, the one entry point for any uploaded image
│   ├── image_processing/          compositor.py plus per-template layout configs
│   ├── vector_db/                 ChromaDB client and few-shot example store
│   ├── db/                        Postgres pool, schema, and all read/write functions
│   ├── storage/                   R2 / local-disk meme storage
│   ├── auth.py, identity.py       Supabase-verified users and anonymous identity
│   ├── arc/                       aura scoring and roast copy
│   ├── memory/                    in-memory per-conversation template history
│   ├── circuit_breaker.py         Groq/Gemini resilience for the LLM call sites
│   ├── telemetry.py               OpenTelemetry metrics and structured logs
│   ├── scripts/                   eval harnesses, trend pipeline, embedding precompute
│   ├── templates/                 120+ meme images, static and animated GIF
│   └── tests/                     pytest suite
│
├── frontend/                      Next.js 14 + Tailwind (TypeScript)
│   └── src/
│       ├── app/                   /, /chat, /lore, /make, /arc, /m/[id], /privacy, /auth
│       ├── components/            ModeTabs, ChatWindow, LoreView, ArcView,
│       │                           ConversationSidebar, AuthControl, LandingPage
│       ├── hooks/                 useMemeStream, shared SSE logic for Chat and Lore
│       └── lib/                   api.ts, identity.ts, supabaseClient.ts
│
├── terraform/                     GCP infrastructure as code
│   └── gke/                       isolated module for a one-shot GKE Autopilot cluster
├── k8s/                           Deployment/Service/HPA/ConfigMap/Secret manifests
├── observability/                 Grafana Cloud dashboard and SLO alerts, exported as JSON
├── integrations/discord-worker/   Cloudflare Worker fronting Discord's /meme command
├── .github/workflows/             CI, deploy, and the weekly trend-discovery pipeline
├── docs/                          infrastructure write-up, uploads, growth-phase summaries
├── scripts/                       template/example seeding, fine-tune data prep
├── docker-compose.yml             Ollama + ChromaDB + backend + frontend, self-hosted
└── render.yaml                    Render Blueprint
```

---

## Quick start

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Local LLM, free and the default. Run in a separate terminal:
ollama pull llama3.1:8b && ollama serve

# OR cloud LLM, no GPU needed:
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

Postgres (`DATABASE_URL`), R2 (`R2_*`), and Supabase Auth (`SUPABASE_URL` and friends) are all optional and feature-flagged. Leaving them unset means local-disk storage, no durable persistence, and anonymous-only use. Nothing crashes without them. See `backend/.env.example`.

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

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat/`, `/chat/image/` | Chat surface, SSE stream, text and/or photos |
| `POST` | `/lore/`, `/lore/image/` | Lore surface, same core, adds `meme_count` and lexicon opt-in |
| `GET` | `/arc` | Personal meme stats |
| `POST` | `/arc/card` | Shareable recap card |
| `GET` | `/explain/` | Every template's metadata, Make's picker |
| `POST` | `/explain/` | One template's metadata and usage history |
| `POST` | `/generate/` | Make: render `template_id` + `texts` directly, moderation-gated |
| `GET` | `/generate/file/{template_id}` | Convenience render, returns the image (or redirects to R2) directly |
| `POST` | `/feedback/` | Thumbs up or down on a generated meme |
| `GET` | `/memes/{id}` | Durable share-page lookup, `/m/{id}` on the frontend |
| `GET` | `/auth/whoami` | Verified identity for the current bearer token |
| `POST` | `/auth/link-anon` | Link anonymous history to a signed-in account |
| `GET` | `/conversations` | List a signed-in user's persisted conversations |
| `POST` | `/conversations` | Start a new persisted conversation |
| `GET` | `/conversations/{id}/messages` | A conversation's full message history |
| `PATCH` | `/conversations/{id}` | Rename a conversation |
| `DELETE` | `/conversations/{id}` | Delete a conversation and its messages |
| `DELETE` | `/me` | Forget-me, erases all data tied to an identity |
| `POST` | `/discord/generate` | Discord `/meme` slash-command backend |
| `POST` | `/share-intake/` | PWA share-target stash |
| `GET` | `/share-intake/{token}/` | PWA share-target retrieve |
| `GET` | `/health` | Liveness check |

### `POST /chat/`, an SSE stream

```
data: {"type": "thinking", "stage": "analyzing", "message": "Reading your vibe..."}
data: {"type": "thinking", "stage": "rendering", "template_id": "drake"}
data: {"type": "done", "conversation_id": "...", "message": {"meme_url": "...", "meme_id": "..."}, "template_used": "drake"}
data: {"type": "batch_done", "total": 1, "succeeded": 1}
```

---

## Infrastructure

The backend has been fully migrated to Google Cloud Run, provisioned entirely with Terraform. CI/CD runs through GitHub Actions with Workload Identity Federation, deploying an untrafficked candidate revision that only gets promoted after a real smoke test. Observability runs on OpenTelemetry shipping to Grafana Cloud, with one dashboard and three SLO alerts. All of it has been verified live under real traffic.

The public app currently still serves from Render. Cutover, pointing the frontend's `BACKEND_URL` at Cloud Run, is a deliberate and reversible step being held until launch, not something left undone.

A separate, isolated Terraform module also stood up a real GKE Autopilot cluster once, deployed the production image to it, verified it against a real public LoadBalancer IP with real requests, and tore it down in the same session. The Kubernetes manifests (`k8s/`) and the Terraform module (`terraform/gke/`) stay in the repo as working evidence, not as a second live deployment target.

Real, measured numbers: cold start on Render is around 30 seconds versus roughly 8.9 seconds on Cloud Run, a CI deploy takes about 3 minutes end to end, and running a Kubernetes control plane continuously would cost around $73 a month against Cloud Run's near-zero steady state. Those numbers, the SLO thresholds and why they're set where they are, and one real incident found and fixed along the way are all written up in **[`docs/INFRASTRUCTURE.md`](docs/INFRASTRUCTURE.md)**.

---

## License

MIT, see [LICENSE](LICENSE).
