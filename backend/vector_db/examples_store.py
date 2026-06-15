"""
ChromaDB collection for few-shot meme examples.

Indexed by user message text — at query time, semantically similar past
examples are retrieved and injected into the LLM system prompt so the model
learns from concrete examples rather than instructions alone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import chromadb
from chromadb import Collection

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"
_EXAMPLES_COLLECTION = "meme_examples"

_client: chromadb.ClientAPI | None = None
_collection: Collection | None = None


def _get_collection() -> Collection:
    global _client, _collection
    if _collection is not None:
        return _collection
    _DB_PATH.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(_DB_PATH))
    _collection = _client.get_or_create_collection(
        name=_EXAMPLES_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def upsert_example(
    user_message: str,
    template_id: str,
    texts: dict[str, str],
) -> None:
    """Add or update a few-shot example. Idempotent — keyed by message hash."""
    col = _get_collection()
    example_id = hashlib.sha256(user_message.lower().strip().encode()).hexdigest()[:16]
    col.upsert(
        ids=[example_id],
        documents=[user_message],
        metadatas=[{
            "template_id": template_id,
            "texts": json.dumps(texts),
        }],
    )


def get_similar_examples(query: str, n_results: int = 3) -> list[dict[str, Any]]:
    """Retrieve the N most semantically similar examples for a user message."""
    col = _get_collection()
    count = col.count()
    if count == 0:
        return []
    results = col.query(
        query_texts=[query],
        n_results=min(n_results, count),
    )
    out = []
    for msg, meta in zip(results["documents"][0], results["metadatas"][0]):
        out.append({
            "user_message": msg,
            "template_id": meta["template_id"],
            "texts": json.loads(meta["texts"]),
        })
    return out


def example_count() -> int:
    return _get_collection().count()
