from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from routers import chat, explain, feedback, generate
from vector_db.chroma_client import init_chroma, list_template_ids, upsert_template
from vector_db.examples_store import _get_collection as _init_examples

settings = get_settings()

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _auto_seed_if_empty() -> None:
    """Seed templates from disk on first startup — runs in <5s for 100 templates."""
    existing = set(list_template_ids())
    if existing:
        return
    print("ChromaDB is empty — auto-seeding templates from disk...")
    count = 0
    for img in _TEMPLATES_DIR.iterdir():
        if img.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        tid = img.stem
        if tid in existing:
            continue
        name = tid.replace("_", " ").title()
        upsert_template(tid, name=name, tags=[tid], description=f"Meme template: {name}")
        count += 1
    print(f"Seeded {count} templates into ChromaDB.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_chroma()
    _init_examples()  # pre-warm examples store so first request isn't slow
    _auto_seed_if_empty()
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
