import asyncio
import json
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
from routers import (
    arc,
    auth,
    chat,
    conversations,
    discord,
    explain,
    feedback,
    generate,
    lore,
    me,
    memes,
    share_intake,
)
from uploads.retention import periodic_purge_loop
from vector_db.chroma_client import (
    init_chroma,
    list_template_ids,
    template_document_text,
    upsert_templates_batch,
    upsert_templates_batch_with_embeddings,
)
from vector_db.examples_store import _get_collection as _init_examples
from vector_db.examples_store import seed_examples

settings = get_settings()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_PRECOMPUTED_EMBEDDINGS_PATH = Path(__file__).parent / "data" / "template_embeddings.json"


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

    Deliberately NOT gated on "collection is completely empty": Gemini's
    embedding API can rate-limit hard enough during seeding to exhaust the
    documented 6-attempt retry budget on one chunk, raising an uncaught
    exception that kills every remaining chunk — but if the collection
    isn't empty anymore (an earlier chunk already landed successfully), an
    empty-only guard would mean the catalog stays permanently
    partial forever, since this function would never run again. Instead,
    this runs every startup and the existing per-template `if tid in
    existing: continue` check below makes it naturally idempotent and
    self-healing — a fully-seeded catalog costs one cheap
    list_template_ids() read and does nothing further; a partial one
    fills in exactly what's missing.

    Prefers scripts/precompute_template_embeddings.py's precomputed
    vectors (backend/data/template_embeddings.json) over a live Gemini
    call whenever both are available — template descriptions are static,
    so re-embedding them from scratch on every single restart (Render's
    disk is ephemeral; nothing here survives a restart) is exactly what
    was hammering Gemini's rate limit repeatedly in production. A
    template missing from the precomputed file (new since the last
    precompute run) or Gemini not being configured at all both fall
    through to the original live-embedding path unchanged — this is a
    graceful degrade per-template, not an all-or-nothing switch.
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

    # Precomputed vectors are Gemini's 3072-dim embeddings — only safe to
    # use when this collection is ALSO running Gemini (settings.gemini_api_key
    # set). Local dev's default fallback embedding model uses a different
    # (384-dim) space; mixing dimensions would silently corrupt query-time
    # results. No key configured means every record just falls through to
    # the live path below, exactly as before this change.
    precomputed: dict[str, dict] = {}
    if settings.gemini_api_key and _PRECOMPUTED_EMBEDDINGS_PATH.exists():
        try:
            precomputed = json.loads(_PRECOMPUTED_EMBEDDINGS_PATH.read_text())
        except Exception as exc:
            print(f"  [error] Failed to read {_PRECOMPUTED_EMBEDDINGS_PATH.name}: {exc}", flush=True)

    fast_records = []
    live_records = []
    for r in records:
        entry = precomputed.get(r["template_id"])
        # Only trust a precomputed entry whose document text matches
        # exactly — a stale entry (description changed since the last
        # precompute run) falls through to a live embed instead of
        # silently serving a mismatched vector.
        if entry and entry.get("document") == template_document_text(r["name"], r["description"], r["tags"]):
            fast_records.append({**r, "embedding": entry["embedding"]})
        else:
            live_records.append(r)

    seeded = 0
    if fast_records:
        print(f"{len(fast_records)} template(s) seeded from precomputed embeddings (no Gemini call).", flush=True)
        for i in range(0, len(fast_records), _SEED_CHUNK_SIZE):
            chunk = fast_records[i : i + _SEED_CHUNK_SIZE]
            try:
                upsert_templates_batch_with_embeddings(chunk)
                seeded += len(chunk)
            except Exception as exc:
                print(f"  [error] Failed to seed a precomputed chunk of {len(chunk)} template(s): {exc}", flush=True)

    if live_records:
        print(f"{len(live_records)} template(s) missing from ChromaDB and precomputed embeddings — seeding live...", flush=True)
        for i in range(0, len(live_records), _SEED_CHUNK_SIZE):
            chunk = live_records[i : i + _SEED_CHUNK_SIZE]
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
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    # Deliberately broken — Phase 3 CI/CD negative-path verification (see
    # docs/superpowers/plans/2026-08-29-cloud-migration-phase3-cicd.md,
    # Task 5 Step 3): confirms a failing smoke test never promotes a
    # candidate to live traffic. Reverted in the very next commit.
    raise RuntimeError("deliberate CI verification failure")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
