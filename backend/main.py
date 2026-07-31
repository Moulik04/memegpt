import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import get_settings
from nlp.intent_router import USE_WHEN
from rate_limit import limiter
from routers import chat, explain, feedback, generate, me, memes, share_intake
from uploads.retention import periodic_purge_loop
from vector_db.chroma_client import init_chroma, list_template_ids, upsert_templates_batch
from vector_db.examples_store import _get_collection as _init_examples, seed_examples

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
        # Embed the USE_WHEN scenario text (when available) so RAG matches user
        # messages against usage situations, not just the template's name.
        records.append({
            "template_id": tid,
            "name": name,
            "tags": [tid],
            "description": USE_WHEN.get(tid, f"Meme template: {name}"),
        })
    for i in range(0, len(records), _SEED_CHUNK_SIZE):
        upsert_templates_batch(records[i : i + _SEED_CHUNK_SIZE])
    print(f"Seeded {len(records)} templates into ChromaDB.", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_chroma()
    _init_examples()  # pre-warm examples store so first request isn't slow

    def _sequential_seed():
        # Run template seeding first, then examples — never concurrently.
        # Concurrent ChromaDB embedding model loads can spike past Render's 512MB limit.
        _auto_seed_if_empty()
        # seed_examples() is async (Growth Phase B — it may fetch rehydration
        # rows from Postgres before writing to Chroma) but this whole function
        # runs inside asyncio.to_thread, a plain thread with no event loop of
        # its own — asyncio.run() gives it one just for this call, then the
        # thread carries on synchronously as before.
        asyncio.run(seed_examples())

    asyncio.create_task(asyncio.to_thread(_sequential_seed))
    # Upload retention sweep — Phase 0/1 never write uploads to disk, so this
    # registry stays empty today, but the sweep runs regardless so it's
    # proven working before Phase 3 (video) actually needs it.
    asyncio.create_task(periodic_purge_loop())
    yield


app = FastAPI(
    title="MemeGPT API",
    description="A chatbot that communicates via memes — powered by LLM intent routing, ChromaDB RAG, and Pillow image composition.",
    version="0.2.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(memes.router, prefix="/memes", tags=["memes"])
app.include_router(share_intake.router, prefix="/share-intake", tags=["share"])
app.include_router(me.router, prefix="/me", tags=["me"])


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
