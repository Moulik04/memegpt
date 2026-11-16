"""
GET /health/db reads one row from a real table, so a ping three times a day
keeps Supabase's free tier from pausing the project. The pool is always mocked
here; no test opens a real connection. /health itself must stay
database-free, because the container healthcheck and the deploy smoke test
call it.
"""

from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

import main
from db import pool as db_pool
from main import app


class FakePool:
    def __init__(self, result="example-1", error: Exception | None = None, hang: bool = False):
        self.queries: list[str] = []
        self._result = result
        self._error = error
        self._hang = hang

    async def fetchval(self, query, *args):
        self.queries.append(query)
        if self._hang:
            await asyncio.sleep(60)
        if self._error is not None:
            raise self._error
        return self._result


def _serve(monkeypatch, pool):
    async def fake_get_pool():
        return pool

    monkeypatch.setattr(db_pool, "get_pool", fake_get_pool)


async def _get(path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


async def test_ok_when_the_query_answers(monkeypatch):
    pool = FakePool()
    _serve(monkeypatch, pool)
    resp = await _get("/health/db")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert pool.queries == ["SELECT id FROM few_shot_examples LIMIT 1"]


async def test_ok_when_the_table_is_empty(monkeypatch):
    _serve(monkeypatch, FakePool(result=None))
    resp = await _get("/health/db")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_503_when_no_database_is_configured(monkeypatch):
    _serve(monkeypatch, None)
    resp = await _get("/health/db")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}


async def test_503_when_the_query_fails(monkeypatch, capsys):
    _serve(monkeypatch, FakePool(error=OSError("could not reach db.example.supabase.co")))
    resp = await _get("/health/db")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}
    # The log line names the error type and never its text.
    out = capsys.readouterr().out
    assert "OSError" in out
    assert "supabase.co" not in out


async def test_503_when_getting_the_pool_fails(monkeypatch):
    async def broken_get_pool():
        raise ConnectionRefusedError()

    monkeypatch.setattr(db_pool, "get_pool", broken_get_pool)
    resp = await _get("/health/db")
    assert resp.status_code == 503


async def test_503_when_the_query_hangs(monkeypatch):
    monkeypatch.setattr(main, "_DB_HEALTH_TIMEOUT_S", 0.05)
    _serve(monkeypatch, FakePool(hang=True))
    resp = await _get("/health/db")
    assert resp.status_code == 503


async def test_health_never_touches_the_database(monkeypatch):
    async def must_not_be_called():
        raise AssertionError("/health asked for the database pool")

    monkeypatch.setattr(db_pool, "get_pool", must_not_be_called)
    resp = await _get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "memegpt-backend"}
