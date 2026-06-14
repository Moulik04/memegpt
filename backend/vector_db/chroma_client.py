"""
ChromaDB client — singleton wrapper used throughout the backend.

Collections:
  meme_templates  — one document per template; queried for RAG context.

Each document is a natural-language description of the template so that
ChromaDB's default embedding model (all-MiniLM-L6-v2 via sentence-transformers)
can surface semantically relevant results from plain-English user messages.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
from chromadb import Collection

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"

_client: chromadb.ClientAPI | None = None
_collection: Collection | None = None

COLLECTION_NAME = "meme_templates"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def init_chroma() -> None:
    global _client, _collection
    _DB_PATH.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(_DB_PATH))
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _get_collection() -> Collection:
    if _collection is None:
        init_chroma()
    assert _collection is not None
    return _collection


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def upsert_template(
    template_id: str,
    name: str,
    tags: list[str],
    description: str = "",
) -> None:
    """Insert or update a template's searchable document in ChromaDB."""
    col = _get_collection()
    document = f"{name}. {description}. Tags: {', '.join(tags)}."
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
        "ts": datetime.now(tz=timezone.utc).isoformat(),
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
    """Semantic search over template documents. Returns ranked results."""
    col = _get_collection()
    count = col.count()
    if count == 0:
        return []

    results = col.query(
        query_texts=[query],
        n_results=min(n_results, count),
    )

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
