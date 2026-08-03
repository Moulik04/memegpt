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
        self.fetch_calls: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.fetch_return: list[dict] = []
        self.fetchrow_return: dict | None = None
        self.execute_status: str = "UPDATE 1"

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return self.execute_status

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
        return [FakeRecord(r) for r in self.fetch_return]

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        return FakeRecord(self.fetchrow_return) if self.fetchrow_return is not None else None

    def acquire(self):
        return _AcquireCM(self)


class _AcquireCM:
    """Fakes pool.acquire()'s async context manager, returning a FakeConn
    bound to the same pool so query capture (self.executed) works
    identically whether a test goes through pool.execute() directly or the
    conn.transaction() path (delete_anon_user_data, migrate_anon_data_to_user)."""

    def __init__(self, pool: "FakePool"):
        self.pool = pool

    async def __aenter__(self) -> "FakeConn":
        return FakeConn(self.pool)

    async def __aexit__(self, *exc_info):
        return False


class FakeConn:
    def __init__(self, pool: "FakePool"):
        self.pool = pool

    async def execute(self, query, *args):
        return await self.pool.execute(query, *args)

    def transaction(self):
        return _NoopTransactionCM()


class _NoopTransactionCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


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
    fake_pool.fetchrow_return = {
        "id": "abc1234567", "url": "https://example.com/x.png", "template_id": "drake", "mode": "context",
    }
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.fetch_meme("abc1234567")
    assert result == {
        "id": "abc1234567", "url": "https://example.com/x.png", "template_id": "drake", "mode": "context",
    }


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


# --- Growth Phase H, Stage 2 — dual-key (anon_user_id / user_id) personalization ---


async def test_insert_meme_issues_correct_sql_with_user_id(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_meme(
        "abc1234567", "/static/generated/abc1234567.png", "drake", "context",
        anon_user_id="anon-1", user_id="user-1",
    )

    query, args = fake_pool.executed[0]
    assert "user_id" in query
    assert "anon-1" in args
    assert "user-1" in args


async def test_insert_feedback_issues_correct_sql_with_user_id(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_feedback("abc1234567", "up", anon_user_id="anon-1", user_id="user-1")

    query, args = fake_pool.executed[0]
    assert "user_id" in query
    assert "user-1" in args


async def test_fetch_recent_templates_for_user_keys_by_user_id_when_present(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.fetch_recent_templates_for_user("anon-1", "user-1")

    query, args = fake_pool.fetch_calls[0]
    assert "user_id = $1" in query
    assert "anon_user_id" not in query
    assert args[0] == "user-1"


async def test_fetch_recent_templates_for_user_falls_back_to_anon_id(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.fetch_recent_templates_for_user("anon-1", None)

    query, args = fake_pool.fetch_calls[0]
    assert "anon_user_id = $1" in query
    assert args[0] == "anon-1"


async def test_fetch_recent_templates_for_user_empty_with_neither_id(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.fetch_recent_templates_for_user(None, None)

    assert result == []
    assert fake_pool.fetch_calls == []


async def test_fetch_humor_profile_keys_by_user_id_when_present(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetch_return = [
        {"template_id": "drake", "up_count": 3, "down_count": 0},
    ]
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.fetch_humor_profile("anon-1", "user-1")

    query, args = fake_pool.fetch_calls[0]
    assert "user_id = $1" in query
    assert args[0] == "user-1"


async def test_fetch_lexicon_keys_by_user_id_when_present(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"terms": json.dumps(["Big Steve"])}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.fetch_lexicon("anon-1", "user-1")

    query, args = fake_pool.fetchrow_calls[0]
    assert "user_id = $1" in query
    assert args[0] == "user-1"
    assert result == ["Big Steve"]


async def test_fetch_lexicon_falls_back_to_anon_id(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"terms": json.dumps(["Big Steve"])}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.fetch_lexicon("anon-1", None)

    query, args = fake_pool.fetchrow_calls[0]
    assert "anon_user_id = $1" in query
    assert args[0] == "anon-1"


async def test_upsert_lexicon_stamps_user_id_via_coalesce(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = None
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.upsert_lexicon("anon-1", ["Big Steve"], user_id="user-1")

    # The lookup uses fetch_lexicon(anon_user_id, user_id) first, then the
    # actual write is the (only) executed statement.
    query, args = fake_pool.executed[0]
    assert "INSERT INTO lore_lexicon" in query
    assert "COALESCE(EXCLUDED.user_id" in query
    assert args[0] == "anon-1"
    assert args[2] == "user-1"


async def test_fetch_personalization_empty_with_neither_id(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)

    ctx = await db.fetch_personalization(None, None)

    assert ctx.anon_user_id is None
    assert ctx.user_id is None
    assert ctx.avoid_templates == []


async def test_fetch_personalization_threads_user_id_through(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    ctx = await db.fetch_personalization("anon-1", "user-1")

    assert ctx.anon_user_id == "anon-1"
    assert ctx.user_id == "user-1"
    # Every underlying fetch should have keyed off user_id, not anon_user_id.
    for query, args in fake_pool.fetch_calls + fake_pool.fetchrow_calls:
        assert "user_id = $1" in query
        assert args[0] == "user-1"


async def test_migrate_anon_data_to_user_noops_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)

    result = await db.migrate_anon_data_to_user("anon-1", "user-1")

    assert result == 0


async def test_migrate_anon_data_to_user_issues_idempotent_updates_and_counts_rows(monkeypatch):
    fake_pool = FakePool()
    fake_pool.execute_status = "UPDATE 1"
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    total = await db.migrate_anon_data_to_user("anon-1", "user-1")

    assert total == 3  # memes + feedback + lore_lexicon, one row each
    tables_touched = set()
    for query, args in fake_pool.executed:
        assert "WHERE anon_user_id = $1 AND user_id IS NULL" in query
        assert args == ("anon-1", "user-1")
        tables_touched.add(query.split()[1])  # "UPDATE <table>"
    assert tables_touched == {"memes", "feedback", "lore_lexicon"}


async def test_migrate_anon_data_to_user_zero_rows_when_nothing_to_link(monkeypatch):
    fake_pool = FakePool()
    fake_pool.execute_status = "UPDATE 0"
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    total = await db.migrate_anon_data_to_user("anon-1", "user-1")

    assert total == 0
