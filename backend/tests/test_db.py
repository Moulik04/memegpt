"""
db/__init__.py — Growth Phase B's Postgres layer. Covers: every write/read
function no-ops gracefully with no DATABASE_URL (the default, and the only
configuration every other test in this suite runs under), and — with a
mocked pool, never a real Postgres connection — that the right SQL gets
issued with the right arguments when a pool is available.
"""

from __future__ import annotations

import json

import db


class FakePool:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self.fetch_return: list[dict] = []
        self.fetchrow_return: dict | None = None

    async def execute(self, query, *args):
        self.executed.append((query, args))

    async def fetch(self, query, *args):
        return [FakeRecord(r) for r in self.fetch_return]

    async def fetchrow(self, query, *args):
        return FakeRecord(self.fetchrow_return) if self.fetchrow_return is not None else None


class FakeRecord(dict):
    """asyncpg Records support both dict-style and attribute access in
    practice this codebase only uses row["col"] — a plain dict subclass is
    enough to fake that."""


async def test_insert_meme_noops_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)
    await db.insert_meme("abc1234567", "/static/generated/abc1234567.png", "drake", "context")
    # No exception raised is the assertion — there's nothing else to check
    # with no pool.


async def test_insert_feedback_noops_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)
    await db.insert_feedback("abc1234567", "up", "conv-1")


async def test_fetch_few_shot_examples_empty_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)
    assert await db.fetch_few_shot_examples() == []


async def test_fetch_meme_none_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)
    assert await db.fetch_meme("abc1234567") is None


async def test_insert_meme_issues_correct_sql(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_meme("abc1234567", "/static/generated/abc1234567.png", "drake", "context")

    assert len(fake_pool.executed) == 1
    query, args = fake_pool.executed[0]
    assert "INSERT INTO memes" in query
    assert args[:4] == ("abc1234567", "/static/generated/abc1234567.png", "drake", "context")


async def test_insert_feedback_issues_correct_sql(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_feedback("abc1234567", "down", "conv-1")

    assert len(fake_pool.executed) == 1
    query, args = fake_pool.executed[0]
    assert "INSERT INTO feedback" in query
    assert args[:3] == ("abc1234567", "down", "conv-1")


async def test_insert_few_shot_example_issues_correct_sql(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_few_shot_example("hash123", "waiting forever", "waiting_skeleton", {"top_text": "x"})

    assert len(fake_pool.executed) == 1
    query, args = fake_pool.executed[0]
    assert "INSERT INTO few_shot_examples" in query
    assert args[0] == "hash123"
    assert args[1] == "waiting forever"
    assert args[2] == "waiting_skeleton"
    assert json.loads(args[3]) == {"top_text": "x"}


async def test_fetch_few_shot_examples_deserializes_texts(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetch_return = [
        {"id": "hash1", "user_message": "msg", "template_id": "drake", "texts": json.dumps({"a": "b"})}
    ]
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    rows = await db.fetch_few_shot_examples()
    assert rows == [{"id": "hash1", "user_message": "msg", "template_id": "drake", "texts": {"a": "b"}}]


async def test_fetch_meme_returns_row(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"id": "abc1234567", "url": "https://example.com/x.png", "template_id": "drake"}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.fetch_meme("abc1234567")
    assert result == {"id": "abc1234567", "url": "https://example.com/x.png", "template_id": "drake"}


async def test_fetch_meme_none_when_not_found(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = None
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.fetch_meme("nonexistent") is None


async def _no_pool():
    return None


def _pool_factory(fake_pool: FakePool):
    async def _get():
        return fake_pool
    return _get
