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

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from db.pool import get_pool


async def insert_meme(
    meme_id: str,
    url: str,
    template_id: str | None,
    mode: str,
    anon_user_id: str | None = None,
    surface: str | None = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO memes (id, url, template_id, mode, anon_user_id, surface, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (id) DO NOTHING
        """,
        meme_id, url, template_id, mode, anon_user_id, surface, datetime.now(timezone.utc),
    )


async def insert_feedback(
    meme_id: str | None,
    rating: str,
    conversation_id: str | None = None,
    anon_user_id: str | None = None,
    template_id: str | None = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO feedback (meme_id, rating, conversation_id, anon_user_id, template_id, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        meme_id, rating, conversation_id, anon_user_id, template_id, datetime.now(timezone.utc),
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
    nothing durable to serve without Postgres. `mode` (Growth Phase D) lets
    the share-page router give Arc cards their own title instead of the
    generic meme one."""
    pool = await get_pool()
    if pool is None:
        return None
    row = await pool.fetchrow(
        "SELECT id, url, template_id, mode FROM memes WHERE id = $1", meme_id
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "url": row["url"],
        "template_id": row["template_id"],
        "mode": row["mode"],
    }


# --- Growth Phase C — anonymous identity + memory v1 ---

async def fetch_recent_templates_for_user(anon_user_id: str, n: int = 5) -> list[str]:
    """Cross-session half of avoid_templates — memory/conversation_store.py
    already covers the in-memory, per-conversation half. [] when Postgres
    is absent, same graceful-absence contract as everything else here."""
    pool = await get_pool()
    if pool is None:
        return []
    rows = await pool.fetch(
        """
        SELECT template_id FROM memes
        WHERE anon_user_id = $1 AND template_id IS NOT NULL
        ORDER BY created_at DESC
        LIMIT $2
        """,
        anon_user_id, n,
    )
    return [row["template_id"] for row in rows]


# A template needs at least this many same-direction ratings to count as a
# real signal (one stray downvote shouldn't poison a profile), and a user
# needs at least this much total feedback before a profile is shown at all.
_HUMOR_MIN_TOTAL_FEEDBACK = 3
_HUMOR_PER_TEMPLATE_THRESHOLD = 2
_HUMOR_TOP_N = 3


async def fetch_humor_profile(anon_user_id: str) -> tuple[list[str], list[str]] | None:
    """(loved_template_ids, hated_template_ids), top _HUMOR_TOP_N each by
    rating count. None — not (\"[]\", \"[]\") — when there's no pool, no
    signal at all, or the signal is too thin to be confident in; parse_intent
    treats None/empty the same way (skips the humor_block entirely)."""
    pool = await get_pool()
    if pool is None:
        return None
    rows = await pool.fetch(
        """
        SELECT template_id,
               COUNT(*) FILTER (WHERE rating = 'up') AS up_count,
               COUNT(*) FILTER (WHERE rating = 'down') AS down_count
        FROM feedback
        WHERE anon_user_id = $1 AND template_id IS NOT NULL
        GROUP BY template_id
        """,
        anon_user_id,
    )
    if sum(row["up_count"] + row["down_count"] for row in rows) < _HUMOR_MIN_TOTAL_FEEDBACK:
        return None

    loved = sorted(
        (r for r in rows if r["up_count"] >= _HUMOR_PER_TEMPLATE_THRESHOLD and r["up_count"] > r["down_count"]),
        key=lambda r: r["up_count"],
        reverse=True,
    )
    hated = sorted(
        (r for r in rows if r["down_count"] >= _HUMOR_PER_TEMPLATE_THRESHOLD and r["down_count"] > r["up_count"]),
        key=lambda r: r["down_count"],
        reverse=True,
    )
    loved_ids = [r["template_id"] for r in loved[:_HUMOR_TOP_N]]
    hated_ids = [r["template_id"] for r in hated[:_HUMOR_TOP_N]]
    if not loved_ids and not hated_ids:
        return None
    return loved_ids, hated_ids


_LEXICON_MAX_TERMS = 40  # bounds future prompt-injection size


async def fetch_lexicon(anon_user_id: str) -> list[str]:
    """[] when Postgres is absent, the user has no row, or opted out —
    the Lore lexicon feature (nlp/lexicon.py) is what ever writes a row."""
    pool = await get_pool()
    if pool is None:
        return []
    row = await pool.fetchrow(
        "SELECT terms FROM lore_lexicon WHERE anon_user_id = $1", anon_user_id
    )
    if row is None:
        return []
    return json.loads(row["terms"])


async def upsert_lexicon(anon_user_id: str, new_terms: list[str]) -> None:
    """Merges new_terms into whatever's already stored (new terms take
    priority on the cap), case-insensitive dedupe, capped at
    _LEXICON_MAX_TERMS. Two round trips (fetch then write) rather than a
    jsonb SQL merge expression — deliberately simple, since this only ever
    runs from a fire-and-forget background task where latency doesn't
    matter (see nlp/lexicon.py)."""
    pool = await get_pool()
    if pool is None or not new_terms:
        return
    existing = await fetch_lexicon(anon_user_id)

    seen: set[str] = set()
    merged: list[str] = []
    for term in [*new_terms, *existing]:
        key = term.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(term.strip())
    merged = merged[:_LEXICON_MAX_TERMS]

    await pool.execute(
        """
        INSERT INTO lore_lexicon (anon_user_id, terms, updated_at)
        VALUES ($1, $2::jsonb, $3)
        ON CONFLICT (anon_user_id) DO UPDATE SET
            terms = EXCLUDED.terms,
            updated_at = EXCLUDED.updated_at
        """,
        anon_user_id, json.dumps(merged), datetime.now(timezone.utc),
    )


@dataclass
class PersonalizationContext:
    anon_user_id: str | None
    avoid_templates: list[str]
    loved_templates: list[str]
    hated_templates: list[str]
    lexicon: list[str]


async def fetch_personalization(anon_user_id: str | None) -> PersonalizationContext:
    """One bundle for everything routers/chat.py needs to personalize a
    request — a fresh all-empty context (never a shared cached instance)
    when there's no anon id, so every caller can unconditionally read its
    fields without an extra None check. The three underlying fetches are
    independent indexed reads, run concurrently so they add one round-trip
    of latency, not three, ahead of parse_intent's own budget."""
    if not anon_user_id:
        return PersonalizationContext(None, [], [], [], [])

    recent, humor, lexicon = await asyncio.gather(
        fetch_recent_templates_for_user(anon_user_id),
        fetch_humor_profile(anon_user_id),
        fetch_lexicon(anon_user_id),
    )
    loved, hated = humor if humor is not None else ([], [])
    return PersonalizationContext(anon_user_id, recent, loved, hated, lexicon)


async def delete_anon_user_data(anon_user_id: str) -> None:
    """"Forget me" — erases every row tied to this anon id. No-ops if
    Postgres is absent, same as every other function here.

    Runs inside one transaction: partial deletion would be worse than an
    all-or-nothing failure for a user-initiated erase request. feedback
    must be deleted before memes — feedback.meme_id REFERENCES memes(id)
    with no ON DELETE clause (defaults to RESTRICT), so deleting a
    referenced memes row first would fail with a FK violation. The OR
    clause below covers both feedback rows this user posted directly AND
    feedback (from anyone) attached to a meme this user generated."""
    pool = await get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM feedback
                WHERE anon_user_id = $1
                   OR meme_id IN (SELECT id FROM memes WHERE anon_user_id = $1)
                """,
                anon_user_id,
            )
            await conn.execute("DELETE FROM memes WHERE anon_user_id = $1", anon_user_id)
            await conn.execute("DELETE FROM lore_lexicon WHERE anon_user_id = $1", anon_user_id)


# --- Growth Phase D — Arc (personal meme stats) ---
#
# Every query below excludes mode IN ('wrapped', 'arc') — a shared Arc card
# is itself a row in `memes`, and must never inflate the stats of the
# person it's shared with, or its own owner's next Arc. Written as a static
# literal (not interpolated) in each query string, matching this file's
# existing style of never building SQL dynamically.


@dataclass
class RawArcStats:
    """Pure aggregates, no scoring/copy — arc/copy.py turns this into the
    voiced ArcStats API response. total_memes=0 (with every other field at
    its default) is a valid, real state (a real anon user with too little
    data), distinct from `None` (no Postgres pool at all)."""
    total_memes: int = 0
    distinct_templates: int = 0
    chat_count: int = 0
    lore_count: int = 0
    top_templates: list[tuple[str, int]] = field(default_factory=list)  # (template_id, count), desc
    first_date: date | None = None
    last_date: date | None = None
    busiest_date: date | None = None
    busiest_sample_ts: datetime | None = None  # a real created_at from the busiest date
    longest_streak_days: int = 0


def _longest_streak(dates: list[date]) -> int:
    """Longest run of consecutive calendar days in a (possibly unsorted,
    possibly duplicated) list of dates. Pure function — no DB, easy to unit
    test directly."""
    unique_sorted = sorted(set(dates))
    if not unique_sorted:
        return 0
    longest = current = 1
    for prev, curr in zip(unique_sorted, unique_sorted[1:]):
        if (curr - prev).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


async def fetch_raw_arc_stats(anon_user_id: str, tz: str = "UTC") -> RawArcStats | None:
    """None only when Postgres is absent — the caller (arc/copy.py) treats
    that identically to "not enough data yet" (both show the empty state),
    but keeping them distinct here matches every other fetch_* function's
    contract. `tz` is a bind parameter to `AT TIME ZONE`, never
    string-interpolated, so this is injection-safe regardless of what a
    client sends as an IANA zone name."""
    pool = await get_pool()
    if pool is None:
        return None

    totals_row, top_rows, busiest_row, date_rows = await asyncio.gather(
        pool.fetchrow(
            """
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT template_id) AS distinct_templates,
                   COUNT(*) FILTER (WHERE surface = 'chat') AS chat_count,
                   COUNT(*) FILTER (WHERE surface = 'lore') AS lore_count,
                   (MIN(created_at) AT TIME ZONE $2)::date AS first_date,
                   (MAX(created_at) AT TIME ZONE $2)::date AS last_date
            FROM memes
            WHERE anon_user_id = $1 AND mode NOT IN ('wrapped', 'arc')
            """,
            anon_user_id, tz,
        ),
        pool.fetch(
            """
            SELECT template_id, COUNT(*) AS cnt
            FROM memes
            WHERE anon_user_id = $1 AND mode NOT IN ('wrapped', 'arc') AND template_id IS NOT NULL
            GROUP BY template_id
            ORDER BY cnt DESC
            LIMIT 3
            """,
            anon_user_id,
        ),
        pool.fetchrow(
            """
            SELECT d, cnt, last_ts FROM (
                SELECT (created_at AT TIME ZONE $2)::date AS d,
                       COUNT(*) AS cnt,
                       MAX(created_at) AS last_ts
                FROM memes
                WHERE anon_user_id = $1 AND mode NOT IN ('wrapped', 'arc')
                GROUP BY d
            ) sub
            ORDER BY cnt DESC, d DESC
            LIMIT 1
            """,
            anon_user_id, tz,
        ),
        pool.fetch(
            """
            SELECT DISTINCT (created_at AT TIME ZONE $2)::date AS d
            FROM memes
            WHERE anon_user_id = $1 AND mode NOT IN ('wrapped', 'arc')
            """,
            anon_user_id, tz,
        ),
    )

    total = totals_row["total"] if totals_row else 0
    if not total:
        return RawArcStats()

    return RawArcStats(
        total_memes=total,
        distinct_templates=totals_row["distinct_templates"],
        chat_count=totals_row["chat_count"],
        lore_count=totals_row["lore_count"],
        top_templates=[(row["template_id"], row["cnt"]) for row in top_rows],
        first_date=totals_row["first_date"],
        last_date=totals_row["last_date"],
        busiest_date=busiest_row["d"] if busiest_row else None,
        busiest_sample_ts=busiest_row["last_ts"] if busiest_row else None,
        longest_streak_days=_longest_streak([row["d"] for row in date_rows]),
    )
