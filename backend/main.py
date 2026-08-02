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
from routers import arc, chat, discord, explain, feedback, generate, lore, me, memes, share_intake
from uploads.retention import periodic_purge_loop
from vector_db.chroma_client import init_chroma, list_template_ids, upsert_templates_batch
from vector_db.examples_store import _get_collection as _init_examples, seed_examples

settings = get_settings()

_TEMPLATES_DIR = Path(__file__).parent / "templates"


_SEED_CHUNK_SIZE = 20  # caps peak memory during embedding — Render free tier is 512MB


def _auto_seed_if_empty() -> None:
    """
    Seed any templates from disk that aren't already in ChromaDB — chunked
    batched upserts.

    Runs in a background thread (see lifespan below) so it never blocks app
    startup: intent_router falls back to a hardcoded template list while
    this is still running, so /chat/ works immediately even mid-seed.

    Embedding all 100+ templates in a single batch spiked memory past
    Render's free-tier 512MB limit and triggered an OOM restart. Chunking
    into groups of _SEED_CHUNK_SIZE keeps peak memory low while still
    being far faster than one upsert call per template.

    Deliberately NOT gated on "collection is completely empty" — a real
    production incident (Growth Phase G, Discord integration) showed why:
    Gemini's embedding API rate-limited hard enough during seeding to
    exhaust the documented 6-attempt retry budget on one chunk, raising an
    uncaught exception that killed every REMAINING chunk — but because the
    collection wasn't empty anymore (the first successful chunk had already
    landed), an empty-only guard would mean the catalog stays permanently
    partial forever, since this function would never run again. Instead,
    this runs every startup and the existing per-template `if tid in
    existing: continue` check below makes it naturally idempotent and
    self-healing — a fully-seeded catalog costs one cheap
    list_template_ids() read and does nothing further; a partial one
    fills in exactly what's missing.
    """
    existing = set(list_template_ids())
    records = []
    for img in _TEMPLATES_DIR.iterdir():
        if img.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
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

    if not records:
        return

    print(f"{len(records)} template(s) missing from ChromaDB — seeding...", flush=True)
    seeded = 0
    for i in range(0, len(records), _SEED_CHUNK_SIZE):
        chunk = records[i : i + _SEED_CHUNK_SIZE]
        try:
            upsert_templates_batch(chunk)
            seeded += len(chunk)
        except Exception as exc:
            # One rate-limited/failed chunk must not sink every remaining
            # chunk — matches the existing per-item try/except precedent in
            # trend_pipeline.py and _stream_batch. Whatever's still missing
            # gets picked up on the next startup by this same function.
            print(f"  [error] Failed to seed a chunk of {len(chunk)} template(s): {exc}", flush=True)
    print(f"Seeded {seeded}/{len(records)} template(s) into ChromaDB.", flush=True)


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

# Growth Phase D — Arc's "signature template" stat shows the actual template
# thumbnail, which requires the raw catalog images (backend/templates/) to be
# publicly reachable; nothing served them before this (only a curated subset
# gets copied into frontend/public/landing/ at build time, and that doesn't
# cover the ~118-template catalog Arc's top-template stat can land on).
# Registered BEFORE the general /static mount below — Starlette matches Mounts
# by path prefix in registration order and doesn't fall through past a
# matching one, so the more specific prefix must come first or every
# /static/templates/* request would be swallowed (and 404'd) by /static.
app.mount("/static/templates", StaticFiles(directory="templates"), name="template_images")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(lore.router, prefix="/lore", tags=["lore"])
app.include_router(explain.router, prefix="/explain", tags=["explain"])
app.include_router(generate.router, prefix="/generate", tags=["generate"])
app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
app.include_router(memes.router, prefix="/memes", tags=["memes"])
app.include_router(share_intake.router, prefix="/share-intake", tags=["share"])
app.include_router(me.router, prefix="/me", tags=["me"])
app.include_router(arc.router, prefix="/arc", tags=["arc"])
app.include_router(discord.router, prefix="/discord", tags=["discord"])


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
