<div align="center">

# MemeGPT

### A meme-first AI chatbot with RAG-powered retrieval, LLM intent routing, and on-demand image composition

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Ollama](https://img.shields.io/badge/Ollama-Llama_3.1-74AA9C?style=flat-square)](https://ollama.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5-FF6B35?style=flat-square)](https://www.trychroma.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-gray?style=flat-square)](LICENSE)

</div>

---

MemeGPT converts any natural-language message into a contextually appropriate meme. A user types a message; the system routes it through an LLM structured-output pipeline to pick a template and generate captions, renders those captions onto the image using a bounding-box compositor, and returns the result in a real-time chat interface.

The stack was designed to be modular: swap the LLM provider, the vector store, or the frontend independently without touching the others.

---

## Architecture

```
User message
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  POST /chat/   (FastAPI)                            │
│                                                     │
│  ┌─────────────────────┐                            │
│  │  NLP Intent Router  │  Claude API (JSON mode)    │
│  │  nlp/intent_router  │  → template_id             │
│  │                     │  → top_text, bottom_text   │
│  └──────────┬──────────┘                            │
│             │                                       │
│  ┌──────────▼──────────┐                            │
│  │   Vector Search     │  ChromaDB (cosine sim.)    │
│  │   vector_db/chroma  │  semantic meme retrieval   │
│  └──────────┬──────────┘                            │
│             │                                       │
│  ┌──────────▼──────────┐                            │
│  │  Pillow Compositor  │  Impact/Arial font         │
│  │  image_processing/  │  stroke text, wrap, bbox   │
│  └──────────┬──────────┘                            │
│             │  /static/generated/<id>.png           │
└─────────────┼───────────────────────────────────────┘
              │
              ▼
    Next.js 14 Chat UI
    (conversation state, meme display, SSE-ready)
```

---

## Features

- **Structured LLM routing** — Claude returns a typed JSON object (`template_id`, `top_text`, `bottom_text`) validated by Pydantic v2 before any image is touched. No prompt-parsing heuristics.
- **RAG-style meme retrieval** — ChromaDB stores template metadata as natural-language documents and surfaces semantically similar past memes on every turn using cosine-similarity search with `sentence-transformers` embeddings.
- **Bounding-box text compositor** — Pillow compositor resolves Impact → Arial → system fallback font, wraps text to fit strictly within configurable pixel bounding boxes, and draws 8-directional stroke for the classic meme look.
- **Multi-panel template support** — `MemeTemplate` stores an array of `TextBox` objects with arbitrary pixel coordinates, supporting any layout (top/bottom, side-by-side panels, multi-zone).
- **Conversation tracking** — each `/chat/` call logs `top_text`, `bottom_text`, and a `conversation_id` back to ChromaDB metadata so the `/explain/` endpoint can surface usage history.
- **Next.js 14 App Router frontend** — dark-themed chat UI with live conversation state, smooth meme reveal animation, and a `/api/*` rewrite proxy so no backend URL is ever hardcoded in component code.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API framework | FastAPI + Uvicorn | Async-first, auto-generates OpenAPI docs, Pydantic-native |
| LLM | Ollama + Llama 3.1 8B (local) | Runs entirely on-device — zero API cost, no rate limits, works offline |
| Vector store | ChromaDB | Zero-infrastructure, cosine-similarity, persistent on-disk storage |
| Image processing | Pillow (PIL) | Full control over pixel-level text placement and stroke rendering |
| Schema validation | Pydantic v2 | End-to-end type safety from API boundary to compositor inputs |
| Frontend | Next.js 14 (App Router) + TypeScript | Server-component ready, built-in image optimization, `rewrites()` proxy |
| Styling | Tailwind CSS v3 | Utility-first, no CSS files to maintain |

---

## Project Structure

```
memegpt/
├── backend/
│   ├── main.py                   FastAPI app — mounts routers, CORS, static files
│   ├── schemas.py                All Pydantic models (MemeTemplate, TextBox, ChatMessage …)
│   ├── pyproject.toml            Dependencies + Ruff/mypy config
│   │
│   ├── routers/
│   │   ├── chat.py               POST /chat/     — full RAG + compose pipeline
│   │   ├── explain.py            POST /explain/  — template metadata & history
│   │   └── generate.py           POST /generate/ — on-demand generation
│   │
│   ├── image_processing/
│   │   └── compositor.py         Pillow text compositor (font, wrap, stroke, bbox)
│   │
│   ├── vector_db/
│   │   └── chroma_client.py      ChromaDB singleton (upsert, query, log_usage)
│   │
│   ├── nlp/
│   │   └── intent_router.py      Claude → JSON → IntentResponse
│   │
│   ├── templates/                Base meme images (add your own .jpg/.png here)
│   └── fonts/                    Drop Impact.ttf or Arial.ttf here
│
├── frontend/
│   └── src/
│       ├── app/                  Next.js App Router (layout, page, globals.css)
│       ├── components/
│       │   ├── ChatWindow.tsx    Stateful chat container + send logic
│       │   ├── MessageBubble.tsx Per-message bubble with meme display
│       │   └── MemeDisplay.tsx   next/image wrapper for rendered memes
│       ├── lib/api.ts            Typed fetch helpers (sendChat, generateMeme, explainMeme)
│       └── types/index.ts        TypeScript interfaces mirroring backend schemas
│
└── scripts/
    └── dummy_template_test.py    Standalone Pillow PoC — no services required
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.com) — free, runs locally, no account needed

### 1. Start Ollama (one-time setup)

```bash
brew install ollama
ollama pull llama3.1:8b   # ~4.7 GB download, done once
ollama serve               # starts the local inference server
```

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn main:app --reload
```

Swagger UI available at `http://localhost:8000/docs`.

### 3. Seed templates (one-time)

```bash
cd ..
python scripts/seed_templates.py   # downloads 20 meme images, seeds ChromaDB
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Chat UI at `http://localhost:3000`.

### Verify the compositor standalone (no API key needed)

```bash
pip install Pillow
python scripts/dummy_template_test.py
# → scripts/dummy_output.png
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat/` | Send a message, receive a meme (full pipeline) |
| `POST` | `/generate/` | Generate a meme directly from `template_id` + texts |
| `GET` | `/generate/file/{template_id}` | Returns raw image — useful for browser previews |
| `POST` | `/explain/` | Fetch metadata, tags, and usage history for a template |
| `GET` | `/health` | Service liveness check |

### `POST /chat/` — example

**Request**
```json
{
  "message": "My PR got 47 review comments",
  "conversation_id": "abc-123"
}
```

**Response**
```json
{
  "conversation_id": "abc-123",
  "message": {
    "role": "assistant",
    "content": "ME TRYING TO EXPLAIN MY CODE / THE REVIEWER",
    "meme_url": "/static/generated/distracted_boyfriend_3f2a1b9c.png",
    "timestamp": "2026-06-14T21:00:00Z"
  },
  "template_used": "distracted_boyfriend"
}
```

---

## Roadmap

- [ ] Seed script for bulk-loading templates into ChromaDB on startup
- [ ] `POST /templates/upload` — user-uploaded base images with auto-tagging
- [ ] SSE streaming so reasoning text appears before the image renders
- [ ] Conversation history passed back to Claude for multi-turn context
- [ ] Docker Compose with backend + frontend services
- [ ] Rate limiting via `slowapi`
- [ ] Pytest suite with golden-image diff tests for the compositor

---

## License

MIT — see [LICENSE](LICENSE).
