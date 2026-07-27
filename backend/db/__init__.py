"""
Postgres layer (Growth Phase B) — source of truth for memes, feedback, and
few-shot examples ("fixing the amnesia": today these either live only on
ephemeral disk or only in ChromaDB, which is treated as rebuildable, so
real user feedback is silently lost on every redeploy).

Every function here no-ops gracefully when db.pool.get_pool() returns
None (DATABASE_URL unset) — Postgres being absent must never be the only
thing standing between the app and a working request, exactly like R2
being absent falls back to local disk in storage/.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from db.pool import get_pool


async def insert_meme(
    meme_id: str,
    url: str,
    template_id: str | None,
    mode: str,
    anon_user_id: str | None = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO memes (id, url, template_id, mode, anon_user_id, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (id) DO NOTHING
        """,
        meme_id, url, template_id, mode, anon_user_id, datetime.now(timezone.utc),
    )


async def insert_feedback(
    meme_id: str | None,
    rating: str,
    conversation_id: str | None = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO feedback (meme_id, rating, conversation_id, created_at)
        VALUES ($1, $2, $3, $4)
        """,
        meme_id, rating, conversation_id, datetime.now(timezone.utc),
    )


async def insert_few_shot_example(
    example_id: str,
    user_message: str,
    template_id: str,
    texts: dict[str, str],
) -> None:
    """example_id must be the same id vector_db/examples_store.py uses for
    the matching ChromaDB row (sha256 of the normalized user_message) so
    the two stores stay addressable by the same key."""
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO few_shot_examples (id, user_message, template_id, texts, created_at)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        ON CONFLICT (id) DO UPDATE SET
            user_message = EXCLUDED.user_message,
            template_id = EXCLUDED.template_id,
            texts = EXCLUDED.texts
        """,
        example_id, user_message, template_id, json.dumps(texts), datetime.now(timezone.utc),
    )


async def fetch_few_shot_examples() -> list[dict[str, Any]]:
    """Used at startup to rehydrate the ChromaDB examples collection —
    see main.py's _sequential_seed. Empty list (not an error) when
    Postgres is absent or the table is empty."""
    pool = await get_pool()
    if pool is None:
        return []
    rows = await pool.fetch(
        "SELECT id, user_message, template_id, texts FROM few_shot_examples"
    )
    return [
        {
            "id": row["id"],
            "user_message": row["user_message"],
            "template_id": row["template_id"],
            "texts": json.loads(row["texts"]),
        }
        for row in rows
    ]


async def fetch_meme(meme_id: str) -> dict[str, Any] | None:
    """Used by GET /memes/{id} (share pages). None when Postgres is absent
    or the id doesn't exist — the caller 404s either way, since there's
    nothing durable to serve without Postgres."""
    pool = await get_pool()
    if pool is None:
        return None
    row = await pool.fetchrow(
        "SELECT id, url, template_id FROM memes WHERE id = $1", meme_id
    )
    if row is None:
        return None
    return {"id": row["id"], "url": row["url"], "template_id": row["template_id"]}
