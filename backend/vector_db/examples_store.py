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

import db
from config import get_settings

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"
_EXAMPLES_COLLECTION = "meme_examples"

_client: chromadb.ClientAPI | None = None
_collection: Collection | None = None


def _get_collection() -> Collection:
    global _client, _collection
    if _collection is not None:
        return _collection
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
    _collection = _client.get_or_create_collection(
        name=_EXAMPLES_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def _example_id(user_message: str) -> str:
    return hashlib.sha256(user_message.lower().strip().encode()).hexdigest()[:16]


async def upsert_example(
    user_message: str,
    template_id: str,
    texts: dict[str, str],
) -> None:
    """Add or update a few-shot example — writes ChromaDB (used for
    semantic retrieval at request time) and Postgres (Growth Phase B
    source of truth, rehydrated into Chroma on every startup) using the
    same id, so both stores address the same example consistently.
    Idempotent — keyed by a hash of the normalized message."""
    example_id = _example_id(user_message)
    col = _get_collection()
    col.upsert(
        ids=[example_id],
        documents=[user_message],
        metadatas=[{
            "template_id": template_id,
            "texts": json.dumps(texts),
        }],
    )
    await db.insert_few_shot_example(example_id, user_message, template_id, texts)


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


# Curated few-shot examples — seeded on first startup.
# These cover templates the LLM tends to confuse with more popular ones.
_SEED_EXAMPLES: list[tuple[str, str, dict]] = [
    (
        "my inner demon telling me to order pizza at 2am while responsible me says sleep",
        "evil_kermit",
        {"regular_kermit": "Just go to sleep, you have work tomorrow", "evil_kermit": "Order the extra-large pizza with double cheese"},
    ),
    (
        "saying 'residence' instead of 'house'",
        "tuxedo_winnie_the_pooh",
        {"basic": "my house", "fancy": "my place of residence"},
    ),
    (
        "first calm then panic then calm again then panic worse about the exam results",
        "panik_kalm_panik",
        {"panik": "results come out tomorrow", "kalm": "I think I did okay", "panik_2": "I definitely failed"},
    ),
    (
        "two enemies shaking hands because they both hate the same person",
        "epic_handshake",
        {"left_arm": "people who hate pineapple on pizza", "right_arm": "people who love pineapple on pizza", "label": "hating the guy who suggested it"},
    ),
    (
        "calling wifi 'wireless fidelity' like a gentleman",
        "tuxedo_winnie_the_pooh",
        {"basic": "wifi", "fancy": "wireless fidelity"},
    ),
    (
        "me vs my evil side at midnight: sleep or doomscroll reels",
        "evil_kermit",
        {"regular_kermit": "Close your phone and sleep", "evil_kermit": "One more reel won't hurt"},
    ),
    (
        "two rivals agreeing that coffee is better than tea",
        "epic_handshake",
        {"left_arm": "morning people", "right_arm": "night owls", "label": "coffee is life"},
    ),
    (
        "Baburao confidently explaining his jugaad fix for the leaking roof",
        "baburao",
        {"top_text": "Landlord: roof is leaking again", "bottom_text": "Baburao: bhai upar bucket rakh do — sorted"},
    ),
    (
        "Jethalal realizing Babita ji saw what he just did — escalating panic",
        "jethalal_panic",
        {"top_text": "Me doing something embarrassing", "bottom_text": "The moment I realize my boss was watching"},
    ),
    (
        "Dhoni calm while everyone else is panicking about the last over",
        "dhoni_calm",
        {"top_text": "Team needs 20 off 6 balls", "bottom_text": "Dhoni walking in like he's going to the canteen"},
    ),
    (
        "my plan looked great on paper until the last step completely betrayed me",
        "grus_plan",
        {"step_1": "Write the essay the night before", "step_2": "Pull an all-nighter", "step_3": "Submit on time", "step_4": "Submit on time"},
    ),
    (
        "me upgrading from calling it a 'snack' to a 'light culinary refreshment'",
        "tuxedo_winnie_the_pooh",
        {"basic": "snack", "fancy": "light culinary refreshment"},
    ),
    (
        "introverts and extroverts both agreeing that Friday afternoon is sacred",
        "epic_handshake",
        {"left_arm": "introverts", "right_arm": "extroverts", "label": "Friday 5pm is untouchable"},
    ),
    (
        "Circuit scheming with Munna bhai about how to fix everything with one call",
        "circuit_plan",
        {"top_text": "Problem: everything is broken", "bottom_text": "Circuit: bhai ek kaam karte hain"},
    ),
    (
        "telling myself all is well while the project deadline collapses around me",
        "alliswel",
        {"panel_1": "Deadline in 3 days", "panel_2": "Still haven't started", "panel_3": "All is well"},
    ),
]


async def seed_examples() -> None:
    """Seed few-shot examples if the collection is empty. Postgres rows
    (Growth Phase B source of truth) take priority when present — a fresh
    empty Postgres bootstraps from the curated set below (which also
    populates Postgres via upsert_example's dual-write), but once real
    feedback-derived examples exist in Postgres, those are what gets
    rehydrated into Chroma on every subsequent restart, not the static
    seed list."""
    col = _get_collection()
    if col.count() > 0:
        return

    postgres_rows = await db.fetch_few_shot_examples()
    if postgres_rows:
        print(f"Rehydrating {len(postgres_rows)} few-shot examples from Postgres...", flush=True)
        for row in postgres_rows:
            col.upsert(
                ids=[row["id"]],
                documents=[row["user_message"]],
                metadatas=[{"template_id": row["template_id"], "texts": json.dumps(row["texts"])}],
            )
        return

    print("Seeding curated few-shot meme examples...", flush=True)
    for user_msg, template_id, texts in _SEED_EXAMPLES:
        await upsert_example(user_msg, template_id, texts)
    print(f"Seeded {len(_SEED_EXAMPLES)} few-shot examples.", flush=True)
