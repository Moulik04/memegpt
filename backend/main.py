from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from routers import chat, explain, generate
from vector_db.chroma_client import init_chroma
from vector_db.examples_store import _get_collection as _init_examples

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_chroma()
    _init_examples()  # pre-warm examples store so first request isn't slow
    yield


app = FastAPI(
    title="MemeGPT API",
    description="A chatbot that communicates via memes — powered by LLM intent routing, ChromaDB RAG, and Pillow image composition.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(explain.router, prefix="/explain", tags=["explain"])
app.include_router(generate.router, prefix="/generate", tags=["generate"])


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
