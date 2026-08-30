"""
ChromaDB client — singleton wrapper used throughout the backend.

Collections:
  meme_templates  — one document per template; queried for RAG context.

Each document is a natural-language description of the template so semantic
search can surface relevant results from plain-English user messages.
Embedding model: Gemini's `gemini-embedding-2` API (via
gemini_embedding_function.py) when GEMINI_API_KEY is set — offloads the
memory-heavy local embedding model that was previously OOM-crashing
Render's 512MB free tier. Falls back to ChromaDB's default local embedding
model (all-MiniLM-L6-v2) with zero config when no key is set — the
zero-cost local dev path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chromadb
from chromadb import Collection

from config import get_settings
from vector_db.gemini_embedding_function import get_embedding_function

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"

_client: chromadb.ClientAPI | None = None
_collection: Collection | None = None

COLLECTION_NAME = "meme_templates"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def init_chroma() -> None:
    global _client, _collection
    settings = get_settings()
    if settings.chroma_host:
        # Docker / remote mode — connect to ChromaDB server container
        _client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
    else:
        # Local dev mode — embedded persistent store
        _DB_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(_DB_PATH))

    # embedding_function is omitted (not passed as None) when Gemini isn't
    # configured, so ChromaDB's own default local embedding function param
    # takes over exactly as before — zero-config local dev stays unchanged.
    collection_kwargs: dict[str, Any] = {
        "name": COLLECTION_NAME,
        "metadata": {"hnsw:space": "cosine"},
    }
    embedding_function = get_embedding_function(settings)
    if embedding_function is not None:
        collection_kwargs["embedding_function"] = embedding_function
    _collection = _client.get_or_create_collection(**collection_kwargs)


def _get_collection() -> Collection:
    if _collection is None:
        init_chroma()
    assert _collection is not None
    return _collection


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def template_document_text(name: str, description: str, tags: list[str]) -> str:
    """The single source of truth for how a template's searchable document
    string is built — shared by upsert_template()/upsert_templates_batch()
    below AND scripts/precompute_template_embeddings.py, so a precomputed
    embedding can never silently drift from what live embedding would have
    produced for the same template."""
    return f"{name}. {description}. Tags: {', '.join(tags)}."


def upsert_template(
    template_id: str,
    name: str,
    tags: list[str],
    description: str = "",
) -> None:
    """Insert or update a template's searchable document in ChromaDB."""
    col = _get_collection()
    document = template_document_text(name, description, tags)
    col.upsert(
        ids=[template_id],
        documents=[document],
        metadatas=[{
            "name": name,
            "tags": json.dumps(tags),
            "description": description,
            "usage_count": 0,
            "recent_uses": json.dumps([]),
        }],
    )


def upsert_templates_batch(records: list[dict[str, Any]]) -> None:
    """
    Insert or update many templates in a single ChromaDB call.

    One batched embedding-model invocation instead of one per template —
    on a slow/throttled CPU (e.g. Render free tier) this is the difference
    between seconds and minutes for 100 templates.

    Each record: {"template_id": ..., "name": ..., "tags": [...], "description": ...}
    """
    if not records:
        return
    col = _get_collection()
    col.upsert(
        ids=[r["template_id"] for r in records],
        documents=[
            template_document_text(r["name"], r.get("description", ""), r.get("tags", []))
            for r in records
        ],
        metadatas=[
            {
                "name": r["name"],
                "tags": json.dumps(r.get("tags", [])),
                "description": r.get("description", ""),
                "usage_count": 0,
                "recent_uses": json.dumps([]),
            }
            for r in records
        ],
    )


def upsert_templates_batch_with_embeddings(records: list[dict[str, Any]]) -> None:
    """
    Same shape as upsert_templates_batch(), but for records that already
    carry a precomputed `embedding` — passes it straight to ChromaDB's
    `embeddings=` kwarg, which skips invoking the collection's embedding
    function entirely. This is what makes startup seeding not need a live
    Gemini call for templates already covered by
    backend/data/template_embeddings.json (see main.py's
    _auto_seed_if_empty()) — the whole point being to stop hammering
    Gemini's rate limit on every restart just to re-derive vectors for
    text that hasn't changed.

    Each record: {"template_id", "name", "tags", "description", "embedding"}
    Caller's responsibility: only call this when the precomputed
    embeddings' dimensionality actually matches the collection's active
    embedding backend (Gemini) — see main.py's settings.gemini_api_key
    guard. Mixing dimensions silently corrupts query-time results.
    """
    if not records:
        return
    col = _get_collection()
    col.upsert(
        ids=[r["template_id"] for r in records],
        embeddings=[r["embedding"] for r in records],
        documents=[
            template_document_text(r["name"], r.get("description", ""), r.get("tags", []))
            for r in records
        ],
        metadatas=[
            {
                "name": r["name"],
                "tags": json.dumps(r.get("tags", [])),
                "description": r.get("description", ""),
                "usage_count": 0,
                "recent_uses": json.dumps([]),
            }
            for r in records
        ],
    )


def log_usage(
    template_id: str,
    top_text: str,
    bottom_text: str,
    conversation_id: str,
) -> None:
    """Append a usage event to the template's metadata."""
    col = _get_collection()
    try:
        result = col.get(ids=[template_id])
    except Exception:
        return

    if not result["ids"]:
        return

    meta = result["metadatas"][0]
    recent: list[dict[str, Any]] = json.loads(meta.get("recent_uses", "[]"))
    recent.insert(0, {
        "ts": datetime.now(tz=UTC).isoformat(),
        "top_text": top_text,
        "bottom_text": bottom_text,
        "conversation_id": conversation_id,
    })
    # Keep only the 20 most recent uses
    recent = recent[:20]

    col.update(
        ids=[template_id],
        metadatas=[{
            **meta,
            "usage_count": int(meta.get("usage_count", 0)) + 1,
            "recent_uses": json.dumps(recent),
        }],
    )


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def query_similar_memes(query: str, n_results: int = 3) -> list[dict[str, Any]]:
    """Semantic search over template documents. Returns ranked results.

    Never raises — the embedding call (Gemini API, when configured) is a
    network call that can fail independently of everything else in
    parse_intent()'s fallback chain; an empty list here degrades RAG
    quality for one request rather than breaking the documented
    "parse_intent never raises" invariant."""
    col = _get_collection()
    count = col.count()
    if count == 0:
        return []

    try:
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, count),
        )
    except Exception as e:
        print(f"[chroma_client] query_similar_memes embedding call failed: {e}", flush=True)
        return []

    return [
        {
            "id": id_,
            "metadata": meta,
            "distance": dist,
        }
        for id_, meta, dist in zip(
            results["ids"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


def list_template_ids() -> list[str]:
    """Return all template IDs currently stored in ChromaDB."""
    col = _get_collection()
    if col.count() == 0:
        return []
    result = col.get(include=[])
    return list(result["ids"])


def get_template_record(template_id: str) -> dict[str, Any] | None:
    """Fetch the full metadata record for a single template by ID."""
    col = _get_collection()
    try:
        result = col.get(ids=[template_id])
    except Exception:
        return None

    if not result["ids"]:
        return None

    meta = result["metadatas"][0]
    return {
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "tags": json.loads(meta.get("tags", "[]")),
        "usage_count": int(meta.get("usage_count", 0)),
        "recent_uses": json.loads(meta.get("recent_uses", "[]")),
    }


def list_all_template_records() -> list[dict[str, Any]]:
    """Bulk-fetch every template's metadata in one call — one collection
    read instead of N individual get_template_record() calls. Powers the
    manual meme-maker's template picker (Phase 4, GET /explain/). Each
    dict includes template_id alongside the same fields
    get_template_record() returns, parsed the same way."""
    col = _get_collection()
    if col.count() == 0:
        return []
    result = col.get(include=["metadatas"])
    records = []
    for template_id, meta in zip(result["ids"], result["metadatas"]):
        records.append(
            {
                "template_id": template_id,
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "tags": json.loads(meta.get("tags", "[]")),
                "usage_count": int(meta.get("usage_count", 0)),
                "recent_uses": json.loads(meta.get("recent_uses", "[]")),
            }
        )
    return records
