"""
Lazy asyncpg connection pool + schema bootstrap (Growth Phase B).

get_pool() returns None when settings.database_url is empty — every caller
in db/__init__.py checks this and no-ops gracefully, the same
"feature-flagged with graceful absence" pattern already used for R2 and
the optional Anthropic vision fallback. The schema is applied idempotently
on first real connection, not as a separate migration step — no Alembic,
matching this repo's minimalism for a 3-table schema.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg

from config import get_settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_pool: asyncpg.Pool | None = None
_schema_applied = False


async def get_pool() -> asyncpg.Pool | None:
    global _pool, _schema_applied
    settings = get_settings()
    if not settings.database_url:
        return None

    if _pool is None:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)

    if not _schema_applied:
        async with _pool.acquire() as conn:
            await conn.execute(_SCHEMA_PATH.read_text())
        _schema_applied = True

    return _pool


async def close_pool() -> None:
    """For tests / clean shutdown — resets the module-level singleton so a
    fresh pool (and re-applied schema check) is created next time."""
    global _pool, _schema_applied
    if _pool is not None:
        await _pool.close()
    _pool = None
    _schema_applied = False
