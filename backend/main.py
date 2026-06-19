import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from routers import chat, explain, feedback, generate
from vector_db.chroma_client import init_chroma, list_template_ids, upsert_templates_batch
from vector_db.examples_store import _get_collection as _init_examples

settings = get_settings()

_TEMPLATES_DIR = Path(__file__).parent / "templates"


_SEED_CHUNK_SIZE = 20  # caps peak memory during embedding — Render free tier is 512MB


def _auto_seed_if_empty() -> None:
    """
    Seed templates from disk if ChromaDB is empty — chunked batched upserts.

    Runs in a background thread (see lifespan below) so it never blocks app
    startup: intent_router falls back to a hardcoded template list while
    this is still running, so /chat/ works immediately even mid-seed.

    Embedding all 100 templates in a single batch spiked memory past Render's
    free-tier 512MB limit and triggered an OOM restart. Chunking into groups
    of _SEED_CHUNK_SIZE keeps peak memory low while still being far faster
    than one upsert call per template.
    """
    existing = set(list_template_ids())
    if existing:
        return
    print("ChromaDB is empty — auto-seeding templates from disk...", flush=True)
    records = []
    for img in _TEMPLATES_DIR.iterdir():
        if img.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        tid = img.stem
        if tid in existing:
            continue
        name = tid.replace("_", " ").title()
        records.append({
            "template_id": tid,
            "name": name,
            "tags": [tid],
            "description": f"Meme template: {name}",
        })
    for i in range(0, len(records), _SEED_CHUNK_SIZE):
        upsert_templates_batch(records[i : i + _SEED_CHUNK_SIZE])
    print(f"Seeded {len(records)} templates into ChromaDB.", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_chroma()
    _init_examples()  # pre-warm examples store so first request isn't slow
    # Run in a background thread — don't block startup on the embedding
    # model's first-use cost (slow on Render free tier's throttled CPU).
    asyncio.create_task(asyncio.to_thread(_auto_seed_if_empty))
    yield


app = FastAPI(
    title="MemeGPT API",
    description="A chatbot that communicates via memes — powered by LLM intent routing, ChromaDB RAG, and Pillow image composition.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_allow_all_origins else settings.cors_origins,
    allow_credentials=not settings.cors_allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(explain.router, prefix="/explain", tags=["explain"])
app.include_router(generate.router, prefix="/generate", tags=["generate"])
app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "memegpt-backend"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
