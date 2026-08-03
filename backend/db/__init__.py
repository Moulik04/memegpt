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
    user_id: str | None = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO memes (id, url, template_id, mode, anon_user_id, surface, user_id, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (id) DO NOTHING
        """,
        meme_id, url, template_id, mode, anon_user_id, surface, user_id, datetime.now(timezone.utc),
    )


async def insert_feedback(
    meme_id: str | None,
    rating: str,
    conversation_id: str | None = None,
    anon_user_id: str | None = None,
    template_id: str | None = None,
    user_id: str | None = None,
) -> None:
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        """
        INSERT INTO feedback (meme_id, rating, conversation_id, anon_user_id, template_id, user_id, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        meme_id, rating, conversation_id, anon_user_id, template_id, user_id, datetime.now(timezone.utc),
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
# --- Growth Phase H, Stage 2 — every function below also takes an optional
#     user_id and, once signed in, keys EXCLUSIVELY off it (never unions
#     with anon_user_id — see schema.sql's Stage 2 comment for why). ---


def _personalization_key(anon_user_id: str | None, user_id: str | None) -> tuple[str, str] | None:
    """Picks which column to filter on — user_id takes exclusive priority
    when present. The column name is always one of two fixed literals
    chosen here, never client-controlled, so interpolating it into a query
    string (rather than binding it as a parameter, which SQL doesn't allow
    for identifiers anyway) carries no injection risk — same "static
    literal, never interpolated value" precedent already used for the
    mode NOT IN (...) clauses in fetch_raw_arc_stats below."""
    if user_id:
        return "user_id", user_id
    if anon_user_id:
        return "anon_user_id", anon_user_id
    return None


async def fetch_recent_templates_for_user(
    anon_user_id: str | None, user_id: str | None = None, n: int = 5
) -> list[str]:
    """Cross-session half of avoid_templates — memory/conversation_store.py
    already covers the in-memory, per-conversation half. [] when Postgres
    is absent, same graceful-absence contract as everything else here."""
    pool = await get_pool()
    if pool is None:
        return []
    key = _personalization_key(anon_user_id, user_id)
    if key is None:
        return []
    column, value = key
    rows = await pool.fetch(
        f"""
        SELECT template_id FROM memes
        WHERE {column} = $1 AND template_id IS NOT NULL
        ORDER BY created_at DESC
        LIMIT $2
        """,
        value, n,
    )
    return [row["template_id"] for row in rows]


# A template needs at least this many same-direction ratings to count as a
# real signal (one stray downvote shouldn't poison a profile), and a user
# needs at least this much total feedback before a profile is shown at all.
_HUMOR_MIN_TOTAL_FEEDBACK = 3
_HUMOR_PER_TEMPLATE_THRESHOLD = 2
_HUMOR_TOP_N = 3


async def fetch_humor_profile(
    anon_user_id: str | None, user_id: str | None = None
) -> tuple[list[str], list[str]] | None:
    """(loved_template_ids, hated_template_ids), top _HUMOR_TOP_N each by
    rating count. None — not (\"[]\", \"[]\") — when there's no pool, no
    signal at all, or the signal is too thin to be confident in; parse_intent
    treats None/empty the same way (skips the humor_block entirely)."""
    pool = await get_pool()
    if pool is None:
        return None
    key = _personalization_key(anon_user_id, user_id)
    if key is None:
        return None
    column, value = key
    rows = await pool.fetch(
        f"""
        SELECT template_id,
               COUNT(*) FILTER (WHERE rating = 'up') AS up_count,
               COUNT(*) FILTER (WHERE rating = 'down') AS down_count
        FROM feedback
        WHERE {column} = $1 AND template_id IS NOT NULL
        GROUP BY template_id
        """,
        value,
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


async def fetch_lexicon(anon_user_id: str | None, user_id: str | None = None) -> list[str]:
    """[] when Postgres is absent, the user has no row, or opted out —
    the Lore lexicon feature (nlp/lexicon.py) is what ever writes a row.

    lore_lexicon's PK is anon_user_id, not user_id (see schema.sql's Stage 2
    comment), so a user_id lookup can't use the same "one static column"
    helper the other fetch_* functions above use — it queries user_id
    directly and, since more than one anon-keyed row could in principle be
    tagged with the same user_id (e.g. two browsers each linked once),
    picks whichever was updated most recently."""
    pool = await get_pool()
    if pool is None:
        return []
    if user_id:
        row = await pool.fetchrow(
            "SELECT terms FROM lore_lexicon WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
            user_id,
        )
    elif anon_user_id:
        row = await pool.fetchrow(
            "SELECT terms FROM lore_lexicon WHERE anon_user_id = $1", anon_user_id
        )
    else:
        return []
    if row is None:
        return []
    return json.loads(row["terms"])


async def upsert_lexicon(
    anon_user_id: str, new_terms: list[str], user_id: str | None = None
) -> None:
    """Merges new_terms into whatever's already stored (new terms take
    priority on the cap), case-insensitive dedupe, capped at
    _LEXICON_MAX_TERMS. Two round trips (fetch then write) rather than a
    jsonb SQL merge expression — deliberately simple, since this only ever
    runs from a fire-and-forget background task where latency doesn't
    matter (see nlp/lexicon.py).

    anon_user_id stays required (it's the table's actual PRIMARY KEY — see
    schema.sql's Stage 2 comment on why user_id can't be one instead); the
    frontend always sends the anon header regardless of sign-in state, so
    this is never actually missing in practice. user_id, when given, is
    stamped onto that same anon-keyed row via COALESCE so a plain anon-only
    extraction (remember_lore without a prior link-anon call) never
    overwrites an already-linked row's user_id with NULL."""
    pool = await get_pool()
    if pool is None or not new_terms:
        return
    existing = await fetch_lexicon(anon_user_id, user_id)

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
        INSERT INTO lore_lexicon (anon_user_id, terms, user_id, updated_at)
        VALUES ($1, $2::jsonb, $3, $4)
        ON CONFLICT (anon_user_id) DO UPDATE SET
            terms = EXCLUDED.terms,
            user_id = COALESCE(EXCLUDED.user_id, lore_lexicon.user_id),
            updated_at = EXCLUDED.updated_at
        """,
        anon_user_id, json.dumps(merged), user_id, datetime.now(timezone.utc),
    )


@dataclass
class PersonalizationContext:
    anon_user_id: str | None
    avoid_templates: list[str]
    loved_templates: list[str]
    hated_templates: list[str]
    lexicon: list[str]
    user_id: str | None = None


async def fetch_personalization(
    anon_user_id: str | None, user_id: str | None = None
) -> PersonalizationContext:
    """One bundle for everything routers/chat.py needs to personalize a
    request — a fresh all-empty context (never a shared cached instance)
    when there's no identity at all, so every caller can unconditionally
    read its fields without an extra None check. The three underlying
    fetches are independent indexed reads, run concurrently so they add one
    round-trip of latency, not three, ahead of parse_intent's own budget.

    Growth Phase H, Stage 2: user_id, when present, is what the three
    underlying fetches actually key off (see _personalization_key) —
    anon_user_id is still threaded through and stored on the returned
    context (routers/chat.py's insert_meme/insert_feedback calls stamp it
    alongside user_id, never in place of it), just not used for the reads
    once a verified user_id exists."""
    if not anon_user_id and not user_id:
        return PersonalizationContext(anon_user_id=None, avoid_templates=[], loved_templates=[], hated_templates=[], lexicon=[], user_id=None)

    recent, humor, lexicon = await asyncio.gather(
        fetch_recent_templates_for_user(anon_user_id, user_id),
        fetch_humor_profile(anon_user_id, user_id),
        fetch_lexicon(anon_user_id, user_id),
    )
    loved, hated = humor if humor is not None else ([], [])
    return PersonalizationContext(
        anon_user_id=anon_user_id,
        avoid_templates=recent,
        loved_templates=loved,
        hated_templates=hated,
        lexicon=lexicon,
        user_id=user_id,
    )


def _affected_row_count(status: str) -> int:
    """asyncpg's Connection.execute() returns a command-tag string like
    "UPDATE 3" — the trailing token is the row count. Parsed defensively
    (falls back to 0) since this is only ever used for an informational
    "did anything actually get linked" signal, never a correctness check."""
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (ValueError, AttributeError):
        return 0


async def migrate_anon_data_to_user(anon_user_id: str, user_id: str) -> int:
    """Growth Phase H, Stage 2 — links a browser's existing anonymous
    history to a real account on first sign-in. One transaction, same
    precedent as delete_anon_user_data: partial linking would be a worse
    failure mode than all-or-nothing. `WHERE user_id IS NULL` on every
    statement makes this idempotent (safe to call again, e.g. a returning
    user signing in on the same browser) and never reassigns a row already
    linked to a DIFFERENT account (a shared-device edge case) — it just
    silently leaves that row alone rather than fighting over ownership.

    lore_lexicon needs no separate "merge" step, unlike memes/feedback:
    it's already one row per anon_user_id, so stamping user_id onto that
    row (rather than creating a second, user-keyed row) is the entire
    migration — fetch_lexicon(user_id=...) can find it from that point on.

    Returns the total row count actually linked (0 with no pool), purely so
    the caller (POST /auth/link-anon) can report a real migrated=True/False
    rather than an always-True "the function ran" signal."""
    pool = await get_pool()
    if pool is None:
        return 0
    total = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for query in (
                "UPDATE memes SET user_id = $2 WHERE anon_user_id = $1 AND user_id IS NULL",
                "UPDATE feedback SET user_id = $2 WHERE anon_user_id = $1 AND user_id IS NULL",
                "UPDATE lore_lexicon SET user_id = $2 WHERE anon_user_id = $1 AND user_id IS NULL",
            ):
                status = await conn.execute(query, anon_user_id, user_id)
                total += _affected_row_count(status)
    return total


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


async def fetch_raw_arc_stats(
    anon_user_id: str | None, user_id: str | None = None, tz: str = "UTC"
) -> RawArcStats | None:
    """None only when Postgres is absent — the caller (arc/copy.py) treats
    that identically to "not enough data yet" (both show the empty state),
    but keeping them distinct here matches every other fetch_* function's
    contract. `tz` is a bind parameter to `AT TIME ZONE`, never
    string-interpolated, so this is injection-safe regardless of what a
    client sends as an IANA zone name.

    Growth Phase H, Stage 2: keys exclusively off user_id when signed in,
    same _personalization_key precedence as the rest of this section."""
    pool = await get_pool()
    if pool is None:
        return None
    key = _personalization_key(anon_user_id, user_id)
    if key is None:
        return RawArcStats()
    column, value = key

    totals_row, top_rows, busiest_row, date_rows = await asyncio.gather(
        pool.fetchrow(
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT template_id) AS distinct_templates,
                   COUNT(*) FILTER (WHERE surface = 'chat') AS chat_count,
                   COUNT(*) FILTER (WHERE surface = 'lore') AS lore_count,
                   (MIN(created_at) AT TIME ZONE $2)::date AS first_date,
                   (MAX(created_at) AT TIME ZONE $2)::date AS last_date
            FROM memes
            WHERE {column} = $1 AND mode NOT IN ('wrapped', 'arc')
            """,
            value, tz,
        ),
        pool.fetch(
            f"""
            SELECT template_id, COUNT(*) AS cnt
            FROM memes
            WHERE {column} = $1 AND mode NOT IN ('wrapped', 'arc') AND template_id IS NOT NULL
            GROUP BY template_id
            ORDER BY cnt DESC
            LIMIT 3
            """,
            value,
        ),
        pool.fetchrow(
            f"""
            SELECT d, cnt, last_ts FROM (
                SELECT (created_at AT TIME ZONE $2)::date AS d,
                       COUNT(*) AS cnt,
                       MAX(created_at) AS last_ts
                FROM memes
                WHERE {column} = $1 AND mode NOT IN ('wrapped', 'arc')
                GROUP BY d
            ) sub
            ORDER BY cnt DESC, d DESC
            LIMIT 1
            """,
            value, tz,
        ),
        pool.fetch(
            f"""
            SELECT DISTINCT (created_at AT TIME ZONE $2)::date AS d
            FROM memes
            WHERE {column} = $1 AND mode NOT IN ('wrapped', 'arc')
            """,
            value, tz,
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
