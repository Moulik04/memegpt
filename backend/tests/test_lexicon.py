"""
nlp/lexicon.py's Growth Phase H, Stage 4 provenance threading —
_extract_and_store must call db.insert_lexicon_terms (the normalized table
a later per-chat delete unwinds from) only when a verified user_id is
present, alongside the always-unconditional flat-cache upsert_lexicon
write. Tests the pure async logic directly (not the fire-and-forget
asyncio.create_task wrapper) since that's where the actual behavior lives.
"""

from __future__ import annotations

import db
from nlp.lexicon import _extract_and_store


async def test_insert_lexicon_terms_called_when_signed_in(monkeypatch):
    async def fake_extract_lexicon(text):
        return ["Big Steve"]

    upsert_calls = []
    terms_calls = []

    async def fake_upsert_lexicon(anon_user_id, terms, user_id=None):
        upsert_calls.append((anon_user_id, terms, user_id))

    async def fake_insert_lexicon_terms(user_id, conversation_id, terms):
        terms_calls.append((user_id, conversation_id, terms))

    monkeypatch.setattr("nlp.lexicon.extract_lexicon", fake_extract_lexicon)
    monkeypatch.setattr(db, "upsert_lexicon", fake_upsert_lexicon)
    monkeypatch.setattr(db, "insert_lexicon_terms", fake_insert_lexicon_terms)

    await _extract_and_store("anon-1", "some group chat text here", "user-1", "conv-1")

    assert upsert_calls == [("anon-1", ["Big Steve"], "user-1")]
    assert terms_calls == [("user-1", "conv-1", ["Big Steve"])]


async def test_insert_lexicon_terms_skipped_for_anonymous_extraction(monkeypatch):
    async def fake_extract_lexicon(text):
        return ["Big Steve"]

    terms_calls = []

    async def fake_upsert_lexicon(anon_user_id, terms, user_id=None):
        pass

    async def fake_insert_lexicon_terms(user_id, conversation_id, terms):
        terms_calls.append((user_id, conversation_id, terms))

    monkeypatch.setattr("nlp.lexicon.extract_lexicon", fake_extract_lexicon)
    monkeypatch.setattr(db, "upsert_lexicon", fake_upsert_lexicon)
    monkeypatch.setattr(db, "insert_lexicon_terms", fake_insert_lexicon_terms)

    await _extract_and_store("anon-1", "some group chat text here", None, None)

    assert terms_calls == []


async def test_insert_lexicon_terms_tracks_none_conversation_id_when_signed_in(monkeypatch):
    """remember_lore firing outside an active persisted conversation — still
    tracked (per the documented Stage 4 limitation), just with conversation_id
    None so it can never be unwound by a later per-chat delete."""

    async def fake_extract_lexicon(text):
        return ["Big Steve"]

    terms_calls = []

    async def fake_upsert_lexicon(anon_user_id, terms, user_id=None):
        pass

    async def fake_insert_lexicon_terms(user_id, conversation_id, terms):
        terms_calls.append((user_id, conversation_id, terms))

    monkeypatch.setattr("nlp.lexicon.extract_lexicon", fake_extract_lexicon)
    monkeypatch.setattr(db, "upsert_lexicon", fake_upsert_lexicon)
    monkeypatch.setattr(db, "insert_lexicon_terms", fake_insert_lexicon_terms)

    await _extract_and_store("anon-1", "some group chat text here", "user-1", None)

    assert terms_calls == [("user-1", None, ["Big Steve"])]


async def test_nothing_written_when_extraction_finds_no_terms(monkeypatch):
    async def fake_extract_lexicon(text):
        return []

    calls = []

    async def fake_upsert_lexicon(anon_user_id, terms, user_id=None):
        calls.append("upsert")

    async def fake_insert_lexicon_terms(user_id, conversation_id, terms):
        calls.append("insert_terms")

    monkeypatch.setattr("nlp.lexicon.extract_lexicon", fake_extract_lexicon)
    monkeypatch.setattr(db, "upsert_lexicon", fake_upsert_lexicon)
    monkeypatch.setattr(db, "insert_lexicon_terms", fake_insert_lexicon_terms)

    await _extract_and_store("anon-1", "some group chat text here", "user-1", "conv-1")

    assert calls == []
