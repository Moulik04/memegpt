"""
db/pool.py's loop-awareness — a real production bug found 2026-08-05:
main.py's startup seeding calls asyncio.run(seed_examples()) inside a
background thread, creating its own throwaway event loop. If that path
reaches get_pool() first (it runs on every startup), the pool it creates
is bound to a loop that's already destroyed by the time any real request
arrives on the actual server loop — asyncpg's internal locks/futures are
tied to their creating loop, so reusing it raises "Task ... attached to a
different loop". get_pool() must detect this and transparently rebuild.

Mocks asyncpg.create_pool entirely (a fake pool that just tracks calls and
supports the acquire()/execute() shape get_pool() needs) — no real network,
matching this suite's existing zero-secrets contract.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

import db.pool as pool_module
from config import Settings


class _FakeConn:
    async def execute(self, query):
        pass


class _FakeAcquireCM:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *exc_info):
        return False


class _FakePool:
    def __init__(self):
        self.closed = False

    def acquire(self):
        return _FakeAcquireCM()

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_pool_module(monkeypatch):
    """db/pool.py's module-level singleton must not leak between tests —
    same precedent as conftest.py's _reset_circuit_breaker."""
    monkeypatch.setattr(pool_module, "_pool", None)
    monkeypatch.setattr(pool_module, "_pool_loop", None)
    monkeypatch.setattr(pool_module, "_schema_applied", False)
    yield
    pool_module._pool = None
    pool_module._pool_loop = None
    pool_module._schema_applied = False


def _settings_with_db_url() -> Settings:
    return Settings(_env_file=None, database_url="postgresql://fake:fake@localhost/fake")


async def test_get_pool_none_with_no_database_url(monkeypatch):
    monkeypatch.setattr(pool_module, "get_settings", lambda: Settings(_env_file=None))

    assert await pool_module.get_pool() is None


async def test_get_pool_reuses_same_pool_within_one_loop(monkeypatch):
    monkeypatch.setattr(pool_module, "get_settings", _settings_with_db_url)
    create_calls = []

    async def fake_create_pool(*args, **kwargs):
        create_calls.append(1)
        return _FakePool()

    monkeypatch.setattr(pool_module.asyncpg, "create_pool", fake_create_pool)

    pool_a = await pool_module.get_pool()
    pool_b = await pool_module.get_pool()

    assert pool_a is pool_b
    assert len(create_calls) == 1


async def test_get_pool_rebuilds_when_cached_pool_belongs_to_a_different_loop(monkeypatch):
    """Reproduces the exact production race: a pool created on a throwaway
    event loop (main.py's startup-seeding pattern: asyncio.run() inside a
    background thread) must never be handed back to a caller on a
    different loop — get_pool() must detect the mismatch and rebuild."""
    monkeypatch.setattr(pool_module, "get_settings", _settings_with_db_url)
    create_calls = []

    async def fake_create_pool(*args, **kwargs):
        create_calls.append(1)
        return _FakePool()

    monkeypatch.setattr(pool_module.asyncpg, "create_pool", fake_create_pool)

    # Simulate main.py's _sequential_seed(): a background thread runs its
    # own asyncio.run(), which creates and destroys its own event loop.
    def run_on_a_throwaway_loop():
        asyncio.run(pool_module.get_pool())

    thread = threading.Thread(target=run_on_a_throwaway_loop)
    thread.start()
    thread.join()

    assert len(create_calls) == 1  # the background thread's own pool

    # Now the real server loop (this test's own running loop) asks for a
    # pool — must NOT reuse the one bound to the now-dead background
    # thread's loop, and must NOT raise.
    real_pool = await pool_module.get_pool()

    assert real_pool is not None
    assert len(create_calls) == 2  # rebuilt for this loop, not reused
