"""
Lazy asyncpg connection pool + schema bootstrap (Growth Phase B).

get_pool() returns None when settings.database_url is empty — every caller
in db/__init__.py checks this and no-ops gracefully, the same
"feature-flagged with graceful absence" pattern already used for R2 and
the optional Anthropic vision fallback. The schema is applied idempotently
on first real connection, not as a separate migration step — no Alembic,
matching this repo's minimalism for a 3-table schema.

Loop-aware by necessity, not just defensively: main.py's startup seeding
runs _sequential_seed() inside asyncio.to_thread(), and that thread calls
asyncio.run(seed_examples()) — which creates its OWN throwaway event loop
just for that call and destroys it the moment the call returns. If that
seeding path's fetch_few_shot_examples() reaches get_pool() first (it runs
unconditionally on every startup, so it usually does), the pool created
there is bound to that already-dead loop by the time any real request
comes in on the actual server loop. asyncpg's internal locks/futures are
tied to the loop that created them, so reusing that pool from a different
loop fails with "Task ... attached to a different loop" — a real,
previously-undetected bug (DATABASE_URL wasn't reachable in production
before this, so it never got the chance to fire). Tracking which loop the
cached pool belongs to and transparently rebuilding it when the caller is
on a different one fixes this for this specific race and for any future
caller pattern that runs its own event loop the same way.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

from config import get_settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None
_schema_applied = False


async def get_pool() -> asyncpg.Pool | None:
    global _pool, _pool_loop, _schema_applied
    settings = get_settings()
    if not settings.database_url:
        return None

    current_loop = asyncio.get_running_loop()
    if _pool is not None and _pool_loop is not current_loop:
        # The cached pool belongs to a different (likely already-closed)
        # event loop — cannot be closed or reused from here, so just drop
        # the reference and rebuild for this loop. See the module docstring
        # for the exact startup-seeding race this guards against.
        _pool = None
        _schema_applied = False

    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
        _pool_loop = current_loop

    if not _schema_applied:
        async with _pool.acquire() as conn:
            await conn.execute(_SCHEMA_PATH.read_text())
        _schema_applied = True

    return _pool


async def close_pool() -> None:
    """For tests / clean shutdown — resets the module-level singleton so a
    fresh pool (and re-applied schema check) is created next time."""
    global _pool, _pool_loop, _schema_applied
    if _pool is not None:
        await _pool.close()
    _pool = None
    _pool_loop = None
    _schema_applied = False
