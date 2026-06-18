<div align="center">

# MemeGPT

### A meme-first AI chatbot — LLM intent routing, RAG retrieval, and real-time image composition. Runs free, locally or in the cloud.

[![Live Demo](https://img.shields.io/badge/Live_Demo-memegpt--six.vercel.app-7C3AED?style=flat-square)](https://memegpt-six.vercel.app)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Ollama](https://img.shields.io/badge/Ollama-Llama_3.1_8B-74AA9C?style=flat-square)](https://ollama.com)
[![Groq](https://img.shields.io/badge/Groq-Cloud_LLM-F55036?style=flat-square)](https://groq.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-1.x-FF6B35?style=flat-square)](https://www.trychroma.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-gray?style=flat-square)](LICENSE)

</div>

---

MemeGPT converts any natural-language message into a contextually appropriate meme. Type a message; the system routes it through an LLM structured-output pipeline, picks the best template from 100 options via semantic search, renders captions using a pixel-accurate bounding-box compositor, and streams the result back to a dark-themed chat interface in real time.

**[Try it live →](https://memegpt-six.vercel.app)**

Two LLM backends, swappable via `LLM_PROVIDER`: **Ollama** (Llama 3.1 8B, 100% local, zero cost, no API key) for development, or **Groq** (free-tier cloud inference, ~400 tok/s) for production deployment where a GPU isn't available.

---

## Demo

| Prompt | Template chosen |
|---|---|
| `"when the intern pushes directly to main"` | Gru's Plan (4-panel) |
| `"me trying to explain to my parents what I do for work"` | Distracted Boyfriend |
| `"should I go to the gym or just watch Netflix"` | Two Buttons |
| `"when I say I'll start the assignment early but it's due tomorrow"` | This Is Fine |
| `"me pretending I read the terms and conditions"` | Hide the Pain Harold |

---

## Architecture

```
User message
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│  POST /chat/   (FastAPI + SSE streaming)                   │
│                                                            │
│  ┌─────────────────────────┐                              │
│  │  NLP Intent Router      │  Ollama — Llama 3.1 8B       │
│  │  nlp/intent_router.py   │  local structured JSON out   │
│  │                         │  → template_id + captions    │
│  └────────────┬────────────┘                              │
│               │                                            │
│  ┌────────────▼────────────┐                              │
│  │  RAG Template Search    │  ChromaDB cosine similarity  │
│  │  vector_db/             │  semantic meme retrieval     │
│  │  chroma_client.py       │  + few-shot example store    │
│  └────────────┬────────────┘                              │
│               │                                            │
│  ┌────────────▼────────────┐                              │
│  │  Pillow Compositor      │  Anton / Impact font         │
│  │  image_processing/      │  per-template bounding boxes │
│  │  compositor.py          │  8-directional stroke text   │
│  └────────────┬────────────┘                              │
│               │  /static/generated/<uuid>.png             │
└───────────────┼────────────────────────────────────────────┘
                │
                ▼
      Next.js 14 Chat UI  (SSE: thinking → rendering → done)
```

---

## Features

- **Zero-cost local LLM** — Ollama runs Llama 3.1 8B entirely on-device. No API key, no rate limits, works offline. GPU-accelerated on Apple Silicon (Metal) and NVIDIA (CUDA).
- **Structured JSON output** — the model returns a typed JSON object (`template_id`, `texts`, `reasoning`) validated by Pydantic v2 before any image is touched. No regex heuristics. Retry logic handles malformed responses.
- **RAG template retrieval** — ChromaDB indexes 100 templates as natural-language documents. Every request does a cosine-similarity search to find semantically relevant candidates, then merges with a core set — keeping the prompt under 1,300 tokens (fits in Ollama's 4096-token context).
- **Per-template text layout** — `template_configs.py` defines named bounding boxes (in % coordinates) per template ID. The compositor converts to pixels at runtime and auto-shrinks font to fit. Supports arbitrary multi-panel layouts: Drake 2-panel, Gru 4-panel, Boardroom 5-bubble, Distracted Boyfriend 3-label, and more.
- **Classic meme typography** — Anton font (free Impact equivalent, OFL license) with 8-directional stroke pass. Falls back to LiberationSans-Bold → Pillow default.
- **SSE streaming** — `/chat/` yields `thinking → rendering → done` events so the UI updates live as each stage completes.
- **Few-shot RAG examples** — a second ChromaDB collection stores curated (prompt → meme) examples. Semantically similar examples are injected into the system prompt to guide the LLM toward better template choices.
- **Docker Compose stack** — one command brings up backend, frontend, and ChromaDB with persistent named volumes and health checks. Native Ollama on Mac routed via `host.docker.internal` for Metal GPU access.
- **Thumbs up/down feedback** — each generated meme has a feedback endpoint that logs ratings back to ChromaDB for future fine-tuning.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API framework | FastAPI + Uvicorn | Async-first, auto-generates OpenAPI docs, Pydantic-native |
| LLM inference | Ollama (local) / Groq (cloud) | Ollama for free, offline, on-device dev; Groq for free-tier cloud inference in production |
| Vector store | ChromaDB 1.x | Zero-infrastructure, cosine similarity, persistent on-disk |
| Image processing | Pillow (PIL) | Full pixel-level control over text layout and stroke rendering |
| Schema validation | Pydantic v2 | End-to-end type safety from API boundary to compositor inputs |
| Frontend | Next.js 14 + TypeScript | App Router, built-in image optimization, `rewrites()` API proxy |
| Styling | Tailwind CSS v3 | Utility-first, no CSS files to maintain |
| Containerisation | Docker Compose | One-command full-stack startup with health checks and volumes |

---

## Project Structure

```
memegpt/
├── docker-compose.yml              Full stack: backend + frontend + ChromaDB
├── .env.example                    Copy to .env — set OLLAMA_MODEL
│
├── backend/
│   ├── Dockerfile
│   ├── main.py                     FastAPI app — routers, CORS, static files, lifespan
│   ├── schemas.py                  Pydantic v2 models (MemeTemplate, TextBox, ChatMessage…)
│   ├── config.py                   Settings via pydantic-settings (.env / env vars)
│   ├── pyproject.toml              Dependencies + Ruff / mypy config
│   │
│   ├── routers/
│   │   ├── chat.py                 POST /chat/     — SSE streaming pipeline
│   │   ├── explain.py              POST /explain/  — template metadata & history
│   │   ├── generate.py             POST /generate/ — direct meme generation
│   │   └── feedback.py             POST /feedback/ — thumbs up/down logging
│   │
│   ├── image_processing/
│   │   ├── compositor.py           Pillow compositor (font, wrap, bbox, stroke)
│   │   └── template_configs.py     Per-template bounding box definitions (100 templates)
│   │
│   ├── vector_db/
│   │   ├── chroma_client.py        ChromaDB singleton — dual-mode (local + HTTP)
│   │   └── examples_store.py       Few-shot example store (separate collection)
│   │
│   ├── nlp/
│   │   └── intent_router.py        Ollama → JSON → IntentResponse (RAG + retry logic)
│   │
│   ├── templates/                  100 base meme images (.jpg / .png)
│   └── fonts/                      Drop Impact.ttf here to override Anton
│
├── frontend/
│   ├── Dockerfile
│   └── src/
│       ├── app/                    Next.js App Router (layout, page, globals.css)
│       ├── components/
│       │   ├── ChatWindow.tsx      Stateful chat container, SSE consumer, send logic
│       │   ├── MessageBubble.tsx   Per-message bubble (user right, meme left)
│       │   └── MemeDisplay.tsx     next/image wrapper for rendered memes
│       ├── lib/api.ts              Typed fetch helpers (sendChat, generateMeme…)
│       └── types/index.ts          TypeScript interfaces mirroring backend schemas
│
└── scripts/
    ├── seed_templates.py           Seeds all 100 templates into ChromaDB on first run
    ├── colab_ollama_server.ipynb   Run Ollama on Colab T4 GPU via ngrok HTTP tunnel
    ├── bridges2_ollama_service.sh  SLURM job for Ollama on PSC Bridges-2 V100-32GB
    ├── use_remote_ollama.sh        Switch OLLAMA_HOST and restart backend in one command
    ├── finetune_unsloth.py         LoRA fine-tuning with Unsloth (auto-detects T4 / V100)
    ├── prepare_finetune_dataset.py Converts Imgflip 100k CSV → ChatML JSONL
    └── dummy_template_test.py      Standalone Pillow PoC — no services required
```

---

## Quick Start

### Option A — Docker (recommended)

```bash
git clone https://github.com/Moulik04/memegpt.git && cd memegpt
cp .env.example .env

# Start native Ollama first (gets Metal / CUDA GPU access)
brew install ollama          # macOS; see ollama.com for Linux / Windows
ollama pull llama3.1:8b     # ~4.7 GB, one-time download
ollama serve                 # keep this terminal open

# Bring up the full stack
docker compose up -d --build

# Seed templates into ChromaDB (first run only, ~30 seconds)
docker exec memegpt-backend python scripts/seed_templates.py
```

- **Chat UI:** `http://localhost:3000`
- **API docs:** `http://localhost:8000/docs`
- **ChromaDB:** `http://localhost:8001`

### Option B — Native (development)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn main:app --reload          # http://localhost:8000

# Seed (separate terminal, venv active)
python ../scripts/seed_templates.py

# Frontend
cd ../frontend
npm install && npm run dev         # http://localhost:3000
```

### Verify the compositor (no Ollama needed)

```bash
pip install Pillow
python scripts/dummy_template_test.py
# → scripts/dummy_output.png
```

---

## Remote GPU Inference

The backend reads `OLLAMA_HOST` at startup — point it to any Ollama instance.

**Google Colab T4 (free):**
Open `scripts/colab_ollama_server.ipynb` → Runtime → T4 GPU → run all cells → copy the printed URL → run locally:
```bash
./scripts/use_remote_ollama.sh https://xxxx.ngrok-free.app
```

**PSC Bridges-2 V100-32GB:**
```bash
sbatch scripts/bridges2_ollama_service.sh
# Follow the SSH tunnel command printed in the job log, then:
./scripts/use_remote_ollama.sh http://localhost:11434
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat/` | Send a message, receive a meme — SSE stream |
| `POST` | `/generate/` | Generate a meme from `template_id` + `texts` directly |
| `GET` | `/generate/file/{template_id}` | Returns raw template image |
| `POST` | `/explain/` | Template metadata, tags, and usage history |
| `POST` | `/feedback/` | Log thumbs up / down for a generated meme |
| `GET` | `/health` | Liveness check |

### `POST /chat/` — SSE stream

```
data: {"type": "thinking", "stage": "analyzing",  "message": "Reading your vibe..."}
data: {"type": "thinking", "stage": "rendering",  "template_id": "drake", "message": "Crafting the perfect drake meme..."}
data: {"type": "done",     "conversation_id": "…", "message": {"meme_url": "/static/generated/drake_3f2a.png", …}, "template_used": "drake"}
```

---

## Roadmap

- [x] SSE streaming (`thinking → rendering → done`)
- [x] Docker Compose full-stack deployment
- [x] Per-template bounding-box text layout (100 templates)
- [x] RAG pre-filtering to stay within 4096-token Ollama context
- [x] Few-shot example store for improved template selection
- [x] Remote GPU support (Colab T4 + Bridges-2 V100)
- [x] Thumbs up / down feedback endpoint
- [x] Groq cloud LLM backend + production deployment (Render backend, Vercel frontend)
- [ ] `POST /templates/upload` — user-uploaded base images with auto-tagging
- [ ] Conversation history passed back to LLM for multi-turn meme chains
- [ ] Fine-tuned model on Imgflip 100k dataset (scripts ready, training pending)
- [ ] Pytest suite with golden-image diff tests for the compositor
- [ ] Rate limiting via `slowapi`

---

## License

MIT — see [LICENSE](LICENSE).
