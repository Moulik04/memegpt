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
from datetime import UTC, date, datetime
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
        meme_id, url, template_id, mode, anon_user_id, surface, user_id, datetime.now(UTC),
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
        meme_id, rating, conversation_id, anon_user_id, template_id, user_id, datetime.now(UTC),
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
        example_id, user_message, template_id, json.dumps(texts), datetime.now(UTC),
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


def _dedupe_case_insensitive(terms: list[str], cap: int) -> list[str]:
    """Shared by upsert_lexicon (merging new + existing terms) and Stage 4's
    unwind_conversation_contribution (re-deriving the cache from whatever's
    left in lore_lexicon_terms after a per-chat delete) — same
    strip/case-insensitive-dedupe/cap logic, input order sets priority."""
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        key = term.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(term.strip())
        if len(result) >= cap:
            break
    return result


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
    merged = _dedupe_case_insensitive([*new_terms, *existing], _LEXICON_MAX_TERMS)

    await pool.execute(
        """
        INSERT INTO lore_lexicon (anon_user_id, terms, user_id, updated_at)
        VALUES ($1, $2::jsonb, $3, $4)
        ON CONFLICT (anon_user_id) DO UPDATE SET
            terms = EXCLUDED.terms,
            user_id = COALESCE(EXCLUDED.user_id, lore_lexicon.user_id),
            updated_at = EXCLUDED.updated_at
        """,
        anon_user_id, json.dumps(merged), user_id, datetime.now(UTC),
    )


async def insert_lexicon_terms(user_id: str, conversation_id: str | None, terms: list[str]) -> None:
    """Growth Phase H, Stage 4 — the normalized provenance table
    unwind_conversation_contribution() reads from to find exactly which
    terms one conversation contributed. Only ever called alongside
    upsert_lexicon() (the flat read-side cache, unchanged) for signed-in
    extractions — anonymous schedule_lexicon_extraction calls never reach
    this function at all, still only writing the flat cache exactly as
    Phase C shipped. conversation_id may be None (remember_lore fired
    outside an active persisted conversation) — those rows are tracked but,
    per the documented Stage 4 limitation, can never be unwound by a later
    per-chat delete since there's no conversation to match them against."""
    pool = await get_pool()
    if pool is None or not terms:
        return
    now = datetime.now(UTC)
    await pool.executemany(
        "INSERT INTO lore_lexicon_terms (user_id, conversation_id, term, created_at) VALUES ($1, $2, $3, $4)",
        [(user_id, conversation_id, term, now) for term in terms],
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
    make_count: int = 0
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
                   COUNT(*) FILTER (WHERE surface = 'make') AS make_count,
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
        make_count=totals_row["make_count"],
        top_templates=[(row["template_id"], row["cnt"]) for row in top_rows],
        first_date=totals_row["first_date"],
        last_date=totals_row["last_date"],
        busiest_date=busiest_row["d"] if busiest_row else None,
        busiest_sample_ts=busiest_row["last_ts"] if busiest_row else None,
        longest_streak_days=_longest_streak([row["d"] for row in date_rows]),
    )


# --- Persisted chat history (signed-in only) ---
#
# Every ownership-sensitive function below pairs a client-supplied
# conversation_id with a verified user_id (`WHERE id = $1 AND user_id = $2`,
# or an explicit fetch_conversation_owner() check) — a bare conversation_id
# is never trusted as proof of ownership on its own. conversations.id is a
# separate, server-generated id rather than a reuse of the client-
# correlation conversation_id string every ChatRequest/LoreRequest already
# carries, because that string has no server-side ownership registry an
# authorization check could be built on — any client can send any value.


async def create_conversation(user_id: str, surface: str) -> str | None:
    """Returns the new conversation's server-generated id, or None with no
    pool — unlike every anon-side function in this file, Postgres being
    absent here means the feature genuinely can't work, not a graceful
    degrade (the caller, POST /conversations, turns None into a 503)."""
    pool = await get_pool()
    if pool is None:
        return None
    row = await pool.fetchrow(
        "INSERT INTO conversations (user_id, surface) VALUES ($1, $2) RETURNING id",
        user_id, surface,
    )
    return str(row["id"]) if row else None


_CONVERSATION_THUMBNAIL_JOIN = """
    LEFT JOIN LATERAL (
        SELECT mm.url FROM messages msg
        JOIN memes mm ON mm.id = msg.meme_id
        WHERE msg.conversation_id = c.id AND msg.meme_id IS NOT NULL
        ORDER BY msg.created_at ASC LIMIT 1
    ) thumb ON true
"""


async def fetch_conversations(
    user_id: str, surface: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Newest-first by updated_at (real activity, not just creation time) —
    the sidebar's list. [] with no pool, same graceful-absence contract as
    every other fetch_* in this file (unlike create_conversation above,
    an empty list here is a perfectly normal "nothing to show yet" state,
    not a broken feature).

    thumbnail_url is the earliest meme-bearing message's meme url, via a
    LATERAL join (not a subquery in the SELECT list) so it's one row per
    conversation regardless of how many meme-bearing messages exist —
    null for a conversation with no memes yet, not an error."""
    pool = await get_pool()
    if pool is None:
        return []
    if surface:
        rows = await pool.fetch(
            f"""
            SELECT c.id, c.title, c.surface, c.created_at, c.updated_at, thumb.url AS thumbnail_url
            FROM conversations c
            {_CONVERSATION_THUMBNAIL_JOIN}
            WHERE c.user_id = $1 AND c.surface = $2
            ORDER BY c.updated_at DESC
            LIMIT $3
            """,
            user_id, surface, limit,
        )
    else:
        rows = await pool.fetch(
            f"""
            SELECT c.id, c.title, c.surface, c.created_at, c.updated_at, thumb.url AS thumbnail_url
            FROM conversations c
            {_CONVERSATION_THUMBNAIL_JOIN}
            WHERE c.user_id = $1
            ORDER BY c.updated_at DESC
            LIMIT $2
            """,
            user_id, limit,
        )
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "surface": row["surface"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "thumbnail_url": row["thumbnail_url"],
        }
        for row in rows
    ]


async def fetch_conversation_owner(conversation_id: str) -> str | None:
    """The ownership-check primitive fetch_messages below builds on. None
    with no pool OR no such conversation — deliberately indistinguishable,
    same posture as fetch_meme()'s existing None contract."""
    pool = await get_pool()
    if pool is None:
        return None
    row = await pool.fetchrow(
        "SELECT user_id FROM conversations WHERE id = $1", conversation_id
    )
    return row["user_id"] if row else None


async def fetch_conversation(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    """A single ownership-checked conversation row — used by PATCH
    /conversations/{id} to build its response after a rename, without the
    caller needing to re-derive it from the full fetch_conversations() list.
    Same thumbnail_url shape as fetch_conversations() — a rename response
    that dropped it would read as the conversation losing its thumbnail
    until the next full list refetch."""
    pool = await get_pool()
    if pool is None:
        return None
    row = await pool.fetchrow(
        f"""
        SELECT c.id, c.title, c.surface, c.created_at, c.updated_at, thumb.url AS thumbnail_url
        FROM conversations c
        {_CONVERSATION_THUMBNAIL_JOIN}
        WHERE c.id = $1 AND c.user_id = $2
        """,
        conversation_id, user_id,
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "surface": row["surface"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "thumbnail_url": row["thumbnail_url"],
    }


async def fetch_messages(conversation_id: str, user_id: str) -> list[dict[str, Any]] | None:
    """Oldest-first (chronological replay order). None — not [] — when the
    conversation doesn't exist or isn't owned by user_id, so the caller
    (GET /conversations/{id}/messages) can 404 rather than returning an
    empty list for a real conversation that's simply owned by someone else.
    A brand-new, genuinely-owned, zero-message conversation still correctly
    returns [] (checked via a separate ownership query, not inferred from
    row count — a JOIN-based single query can't tell "owned but empty"
    apart from "not owned" by row count alone)."""
    pool = await get_pool()
    if pool is None:
        return None
    owner = await fetch_conversation_owner(conversation_id)
    if owner != user_id:
        return None
    # LEFT JOIN memes for the url directly — avoids an N+1 fetch_meme()
    # call per message with an attached meme, at the cost of one join.
    rows = await pool.fetch(
        """
        SELECT m.id, m.role, m.content, m.meme_id, mm.url AS meme_url, m.created_at
        FROM messages m
        LEFT JOIN memes mm ON mm.id = m.meme_id
        WHERE m.conversation_id = $1
        ORDER BY m.created_at ASC
        """,
        conversation_id,
    )
    return [
        {
            "id": str(row["id"]),
            "role": row["role"],
            "content": row["content"],
            "meme_url": row["meme_url"],
            "meme_id": row["meme_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


async def insert_message(
    conversation_id: str, role: str, content: str, meme_id: str | None = None
) -> None:
    """No ownership check here — this is the hot chat-streaming path
    (routers/chat.py), which only ever calls this after its own
    fetch_conversation_owner() check already succeeded once for the turn;
    re-checking per message would be a redundant query for no safety gain.
    One transaction: the message insert and the updated_at bump (so the
    sidebar's newest-first ordering reflects real activity) succeed or
    fail together."""
    pool = await get_pool()
    if pool is None:
        return
    now = datetime.now(UTC)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, meme_id, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                conversation_id, role, content, meme_id, now,
            )
            await conn.execute(
                "UPDATE conversations SET updated_at = $2 WHERE id = $1",
                conversation_id, now,
            )


async def set_conversation_title_if_unset(conversation_id: str, title: str) -> None:
    """The auto-titling write — only ever sets a title once (the first
    exchange), via the WHERE title IS NULL guard, so it can never clobber a
    user's rename (rename_conversation, below) or a title set by an
    earlier turn."""
    pool = await get_pool()
    if pool is None:
        return
    await pool.execute(
        "UPDATE conversations SET title = $2 WHERE id = $1 AND title IS NULL",
        conversation_id, title,
    )


async def rename_conversation(conversation_id: str, user_id: str, title: str) -> bool:
    """True only if a row was actually renamed (existed AND owned by
    user_id) — PATCH /conversations/{id} 404s on False."""
    pool = await get_pool()
    if pool is None:
        return False
    status = await pool.execute(
        "UPDATE conversations SET title = $3, updated_at = $4 WHERE id = $1 AND user_id = $2",
        conversation_id, user_id, title, datetime.now(UTC),
    )
    return _affected_row_count(status) > 0


async def delete_conversation(conversation_id: str, user_id: str) -> bool:
    """Growth Phase H, Stage 4 — "delete this chat" means forget it ever
    happened, not just hide it from the sidebar: unwinds the conversation's
    contribution to feedback/memes/lore_lexicon before removing the
    conversation itself. Public signature unchanged from Stage 3's simple
    version, so DELETE /conversations/{id} needed no changes at all."""
    return await unwind_conversation_contribution(conversation_id, user_id)


async def unwind_conversation_contribution(conversation_id: str, user_id: str) -> bool:
    """False (no-op, matching every other ownership-checked function's
    contract) with no pool, or when conversation_id doesn't exist or isn't
    owned by user_id — checked FIRST, before any delete runs, so a
    forged/foreign id fails closed rather than partially executing.

    FK-safe ordering (non-obvious — got this wrong in the original plan
    sketch, corrected here):
    1. Collect this conversation's meme_ids from `messages` (read-only,
       before any deletes touch that table).
    2. Delete `feedback` rows referencing those memes. NOT via
       feedback.conversation_id — that column holds the OLD client-
       correlation conversation_id string (from FeedbackRequest), a
       completely different id space than this function's conversation_id
       (conversations.id, server-generated) — the two are never comparable.
       feedback.meme_id -> memes.id has no ON DELETE clause (defaults to
       RESTRICT), so this must run before deleting memes, below.
    3. Delete `lore_lexicon_terms` rows for this conversation_id — must run
       BEFORE deleting the conversation itself: that table's FK is
       ON DELETE SET NULL, so deleting the conversation first would null
       out conversation_id on those rows out from under this exact WHERE
       clause, leaving them un-findable and never actually deleted.
    4. Re-derive lore_lexicon.terms (the flat cache every reader still
       uses) for user_id from whatever lore_lexicon_terms rows are left.
    5. Delete the conversation — cascades `messages` (ON DELETE CASCADE),
       which is what actually clears every messages.meme_id reference to
       the memes this conversation generated.
    6. Only now delete those `memes` rows — safe, since nothing references
       them anymore (messages gone via cascade, feedback already deleted
       in step 2). This un-teaches avoid_templates/humor profile for free:
       both read live off memes/feedback, no separate cache to bust."""
    pool = await get_pool()
    if pool is None:
        return False
    owner = await fetch_conversation_owner(conversation_id)
    if owner != user_id:
        return False

    async with pool.acquire() as conn:
        async with conn.transaction():
            meme_rows = await conn.fetch(
                "SELECT meme_id FROM messages WHERE conversation_id = $1 AND meme_id IS NOT NULL",
                conversation_id,
            )
            meme_ids = [row["meme_id"] for row in meme_rows]

            if meme_ids:
                await conn.execute(
                    "DELETE FROM feedback WHERE meme_id = ANY($1::text[])", meme_ids
                )

            await conn.execute(
                "DELETE FROM lore_lexicon_terms WHERE conversation_id = $1", conversation_id
            )

            remaining = await conn.fetch(
                "SELECT term FROM lore_lexicon_terms WHERE user_id = $1 ORDER BY created_at DESC",
                user_id,
            )
            terms = _dedupe_case_insensitive([r["term"] for r in remaining], _LEXICON_MAX_TERMS)
            await conn.execute(
                "UPDATE lore_lexicon SET terms = $2::jsonb, updated_at = $3 WHERE user_id = $1",
                user_id, json.dumps(terms), datetime.now(UTC),
            )

            status = await conn.execute(
                "DELETE FROM conversations WHERE id = $1 AND user_id = $2", conversation_id, user_id
            )
            deleted = _affected_row_count(status) > 0

            if meme_ids:
                await conn.execute("DELETE FROM memes WHERE id = ANY($1::text[])", meme_ids)

    return deleted
