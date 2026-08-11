"""
db/__init__.py — Growth Phase B's Postgres layer. Covers: every write/read
function no-ops gracefully with no DATABASE_URL (the default, and the only
configuration every other test in this suite runs under), and — with a
mocked pool, never a real Postgres connection — that the right SQL gets
issued with the right arguments when a pool is available.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import db


class FakePool:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list]] = []
        self.fetch_calls: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.fetch_return: list[dict] = []
        self.fetchrow_return: dict | None = None
        self.execute_status: str = "UPDATE 1"

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return self.execute_status

    async def executemany(self, query, args_list):
        self.executemany_calls.append((query, list(args_list)))

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

    async def fetch(self, query, *args):
        return await self.pool.fetch(query, *args)

    async def fetchrow(self, query, *args):
        return await self.pool.fetchrow(query, *args)

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


# --- Growth Phase H, Stage 3 — persisted chat history (conversations/messages) ---


async def test_create_conversation_none_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)

    assert await db.create_conversation("user-1", "chat") is None


async def test_create_conversation_returns_new_id(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"id": "conv-uuid-1"}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.create_conversation("user-1", "chat")

    assert result == "conv-uuid-1"
    query, args = fake_pool.fetchrow_calls[0]
    assert "INSERT INTO conversations" in query
    assert args == ("user-1", "chat")


async def test_fetch_conversations_empty_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)

    assert await db.fetch_conversations("user-1") == []


async def test_fetch_conversations_filters_by_surface(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.fetch_conversations("user-1", surface="lore")

    query, args = fake_pool.fetch_calls[0]
    assert "surface = $2" in query
    assert args == ("user-1", "lore", 50)


async def test_fetch_conversations_returns_rows(monkeypatch):
    fake_pool = FakePool()
    now = datetime.now(timezone.utc)
    fake_pool.fetch_return = [
        {
            "id": "conv-1", "title": "hello", "surface": "chat", "created_at": now, "updated_at": now,
            "thumbnail_url": "/static/generated/abc123.png",
        }
    ]
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    rows = await db.fetch_conversations("user-1")

    assert rows == [
        {
            "id": "conv-1", "title": "hello", "surface": "chat", "created_at": now, "updated_at": now,
            "thumbnail_url": "/static/generated/abc123.png",
        }
    ]


async def test_fetch_conversation_owner_returns_user_id(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "user-1"}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.fetch_conversation_owner("conv-1") == "user-1"


async def test_fetch_conversation_owner_none_when_not_found(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = None
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.fetch_conversation_owner("conv-1") is None


async def test_fetch_messages_none_when_not_owned(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "someone-else"}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.fetch_messages("conv-1", "user-1") is None
    # Never even issued the messages query once ownership failed.
    assert fake_pool.fetch_calls == []


async def test_fetch_messages_returns_rows_when_owned(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "user-1"}
    now = datetime.now(timezone.utc)
    fake_pool.fetch_return = [
        {"id": "msg-1", "role": "user", "content": "hi", "meme_url": None, "meme_id": None, "created_at": now},
    ]
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    rows = await db.fetch_messages("conv-1", "user-1")

    assert rows == [
        {"id": "msg-1", "role": "user", "content": "hi", "meme_url": None, "meme_id": None, "created_at": now}
    ]


async def test_fetch_messages_owned_but_empty_conversation_returns_empty_list(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "user-1"}
    fake_pool.fetch_return = []
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.fetch_messages("conv-1", "user-1") == []


async def test_insert_message_noops_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)

    await db.insert_message("conv-1", "user", "hi")


async def test_insert_message_inserts_and_bumps_updated_at(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_message("conv-1", "assistant", "here's your meme", meme_id="meme-1")

    assert len(fake_pool.executed) == 2
    insert_query, insert_args = fake_pool.executed[0]
    assert "INSERT INTO messages" in insert_query
    assert insert_args[:4] == ("conv-1", "assistant", "here's your meme", "meme-1")
    update_query, update_args = fake_pool.executed[1]
    assert "UPDATE conversations SET updated_at" in update_query
    assert update_args[0] == "conv-1"


async def test_set_conversation_title_if_unset_issues_correct_sql(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.set_conversation_title_if_unset("conv-1", "My new chat")

    query, args = fake_pool.executed[0]
    assert "WHERE id = $1 AND title IS NULL" in query
    assert args == ("conv-1", "My new chat")


async def test_rename_conversation_true_when_row_affected(monkeypatch):
    fake_pool = FakePool()
    fake_pool.execute_status = "UPDATE 1"
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.rename_conversation("conv-1", "user-1", "New title") is True


async def test_rename_conversation_false_when_nothing_matched(monkeypatch):
    fake_pool = FakePool()
    fake_pool.execute_status = "UPDATE 0"
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.rename_conversation("conv-1", "user-1", "New title") is False


async def test_delete_conversation_false_when_not_owned(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "someone-else"}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.delete_conversation("conv-1", "user-1") is False
    # Fails closed BEFORE any delete runs.
    assert fake_pool.executed == []


async def test_delete_conversation_true_when_owned(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "user-1"}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    assert await db.delete_conversation("conv-1", "user-1") is True


async def test_fetch_conversation_returns_owned_row(monkeypatch):
    fake_pool = FakePool()
    now = datetime.now(timezone.utc)
    fake_pool.fetchrow_return = {
        "id": "conv-1", "title": "hi", "surface": "chat", "created_at": now, "updated_at": now,
        "thumbnail_url": None,
    }
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.fetch_conversation("conv-1", "user-1")

    assert result == {
        "id": "conv-1", "title": "hi", "surface": "chat", "created_at": now, "updated_at": now,
        "thumbnail_url": None,
    }


# --- Growth Phase H, Stage 4 — per-chat delete cascade ---


def test_dedupe_case_insensitive_removes_duplicates_ignoring_case():
    result = db._dedupe_case_insensitive(["Big Steve", "big steve", "The Printer Incident"], cap=10)
    assert result == ["Big Steve", "The Printer Incident"]


def test_dedupe_case_insensitive_respects_input_order_as_priority():
    result = db._dedupe_case_insensitive(["b", "a", "b"], cap=10)
    assert result == ["b", "a"]


def test_dedupe_case_insensitive_caps_output():
    result = db._dedupe_case_insensitive(["a", "b", "c", "d"], cap=2)
    assert result == ["a", "b"]


def test_dedupe_case_insensitive_skips_blank_terms():
    result = db._dedupe_case_insensitive(["  ", "a", ""], cap=10)
    assert result == ["a"]


async def test_insert_lexicon_terms_noops_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)

    await db.insert_lexicon_terms("user-1", "conv-1", ["Big Steve"])


async def test_insert_lexicon_terms_noops_with_empty_terms(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_lexicon_terms("user-1", "conv-1", [])

    assert fake_pool.executemany_calls == []


async def test_insert_lexicon_terms_issues_correct_sql(monkeypatch):
    fake_pool = FakePool()
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    await db.insert_lexicon_terms("user-1", "conv-1", ["Big Steve", "the printer incident"])

    assert len(fake_pool.executemany_calls) == 1
    query, args_list = fake_pool.executemany_calls[0]
    assert "INSERT INTO lore_lexicon_terms" in query
    assert len(args_list) == 2
    assert args_list[0][:3] == ("user-1", "conv-1", "Big Steve")
    assert args_list[1][:3] == ("user-1", "conv-1", "the printer incident")


async def test_unwind_conversation_contribution_false_with_no_pool(monkeypatch):
    monkeypatch.setattr(db, "get_pool", _no_pool)

    assert await db.unwind_conversation_contribution("conv-1", "user-1") is False


async def test_unwind_conversation_contribution_false_when_not_owned(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "someone-else"}
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.unwind_conversation_contribution("conv-1", "user-1")

    assert result is False
    assert fake_pool.executed == []


async def test_unwind_conversation_contribution_full_flow_with_memes(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "user-1"}
    # First fetch() call returns this conversation's meme_ids; the second
    # (remaining lore_lexicon_terms after the delete) returns leftover terms.
    fetch_returns = [
        [{"meme_id": "meme-1"}, {"meme_id": "meme-2"}],
        [{"term": "Big Steve"}],
    ]
    call_count = {"n": 0}

    async def fake_fetch(query, *args):
        fake_pool.fetch_calls.append((query, args))
        result = fetch_returns[call_count["n"]]
        call_count["n"] += 1
        return [FakeRecord(r) for r in result]

    fake_pool.fetch = fake_fetch
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.unwind_conversation_contribution("conv-1", "user-1")

    assert result is True
    queries = [q for q, _ in fake_pool.executed]
    assert any("DELETE FROM feedback" in q for q in queries)
    assert any("DELETE FROM lore_lexicon_terms" in q for q in queries)
    assert any("UPDATE lore_lexicon" in q for q in queries)
    assert any("DELETE FROM conversations" in q for q in queries)
    assert any("DELETE FROM memes" in q for q in queries)

    # FK-safe ordering: conversations must be deleted (clearing messages'
    # meme_id references via cascade) BEFORE memes itself is deleted.
    conv_idx = next(i for i, q in enumerate(queries) if "DELETE FROM conversations" in q)
    memes_idx = next(i for i, q in enumerate(queries) if "DELETE FROM memes" in q)
    assert conv_idx < memes_idx

    # lore_lexicon_terms deleted before conversations (ON DELETE SET NULL
    # would otherwise null conversation_id out from under that WHERE clause).
    lexterms_idx = next(i for i, q in enumerate(queries) if "DELETE FROM lore_lexicon_terms" in q)
    assert lexterms_idx < conv_idx

    # feedback deleted before memes (FK: feedback.meme_id -> memes.id).
    feedback_idx = next(i for i, q in enumerate(queries) if "DELETE FROM feedback" in q)
    assert feedback_idx < memes_idx

    # The re-derived cache reflects whatever lore_lexicon_terms rows remained.
    update_query, update_args = next(
        (q, a) for q, a in fake_pool.executed if "UPDATE lore_lexicon" in q
    )
    assert update_args[0] == "user-1"
    assert json.loads(update_args[1]) == ["Big Steve"]


async def test_unwind_conversation_contribution_skips_feedback_and_memes_when_no_memes(monkeypatch):
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "user-1"}
    fake_pool.fetch_return = []  # no memes in this conversation, no leftover lexicon terms
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.unwind_conversation_contribution("conv-1", "user-1")

    assert result is True
    queries = [q for q, _ in fake_pool.executed]
    assert not any("DELETE FROM feedback" in q for q in queries)
    assert not any("DELETE FROM memes" in q for q in queries)
    assert any("DELETE FROM lore_lexicon_terms" in q for q in queries)
    assert any("DELETE FROM conversations" in q for q in queries)


async def test_unwind_conversation_contribution_false_when_conversation_delete_matched_nothing(monkeypatch):
    """A TOCTOU edge case: ownership checked out, but the conversation was
    deleted by something else before the transaction's own DELETE ran —
    the final row count is what decides success, not the earlier check."""
    fake_pool = FakePool()
    fake_pool.fetchrow_return = {"user_id": "user-1"}
    fake_pool.fetch_return = []
    fake_pool.execute_status = "DELETE 0"
    monkeypatch.setattr(db, "get_pool", _pool_factory(fake_pool))

    result = await db.unwind_conversation_contribution("conv-1", "user-1")

    assert result is False
