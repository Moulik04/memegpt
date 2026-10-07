"""
Growth Phase H, Stage 3 — GET/POST/PATCH/DELETE /conversations. Router-level
tests, mocking db.py's functions directly (FakePool-level coverage already
lives in test_db.py) and auth.get_verified_user, matching test_auth.py's
`lambda request: _resolved(...)` pattern for standing in for an async
dependency without a real Supabase call.
"""

from __future__ import annotations

from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

import db
import storage
from auth import VerifiedUser
from main import app


async def _resolved(value):
    return value


def _mock_verified_user(monkeypatch, user_id: str | None):
    value = VerifiedUser(user_id=user_id, email=None) if user_id else None
    monkeypatch.setattr("routers.conversations.get_verified_user", lambda request: _resolved(value))


async def _get(path: str, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers or {})


async def _post(path: str, json: dict | None = None, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=json or {}, headers=headers or {})


async def _patch(path: str, json: dict, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch(path, json=json, headers=headers or {})


async def _delete(path: str, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.delete(path, headers=headers or {})


# --- GET /conversations ---


async def test_list_conversations_empty_when_unauthenticated(monkeypatch):
    _mock_verified_user(monkeypatch, None)

    resp = await _get("/conversations")

    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_conversations_returns_rows(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")
    now = datetime.now(UTC)

    async def fake_fetch_conversations(user_id, surface=None, limit=50):
        assert user_id == "user-1"
        return [{"id": "conv-1", "title": "hi", "surface": "chat", "created_at": now, "updated_at": now}]

    monkeypatch.setattr(db, "fetch_conversations", fake_fetch_conversations)

    resp = await _get("/conversations")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "conv-1"


# --- POST /conversations ---


async def test_create_conversation_requires_auth(monkeypatch):
    _mock_verified_user(monkeypatch, None)

    resp = await _post("/conversations", json={"surface": "chat"})

    assert resp.status_code == 401


async def test_create_conversation_success(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")

    async def fake_create_conversation(user_id, surface):
        assert user_id == "user-1"
        assert surface == "lore"
        return "new-conv-id"

    monkeypatch.setattr(db, "create_conversation", fake_create_conversation)

    resp = await _post("/conversations", json={"surface": "lore"})

    assert resp.status_code == 200
    assert resp.json() == {"id": "new-conv-id", "surface": "lore"}


async def test_create_conversation_503_with_no_pool(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")

    async def fake_create_conversation(user_id, surface):
        return None

    monkeypatch.setattr(db, "create_conversation", fake_create_conversation)

    resp = await _post("/conversations", json={"surface": "chat"})

    assert resp.status_code == 503


# --- GET /conversations/{id}/messages ---


async def test_get_messages_404_when_unauthenticated(monkeypatch):
    _mock_verified_user(monkeypatch, None)

    resp = await _get("/conversations/conv-1/messages")

    assert resp.status_code == 404


async def test_get_messages_404_when_not_found_or_not_owned(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")

    async def fake_fetch_messages(conversation_id, user_id):
        return None

    monkeypatch.setattr(db, "fetch_messages", fake_fetch_messages)

    resp = await _get("/conversations/someone-elses-conv/messages")

    assert resp.status_code == 404


async def test_get_messages_returns_list(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")
    now = datetime.now(UTC)

    async def fake_fetch_messages(conversation_id, user_id):
        assert conversation_id == "conv-1"
        assert user_id == "user-1"
        return [{"id": "msg-1", "role": "user", "content": "hi", "meme_url": None, "created_at": now}]

    monkeypatch.setattr(db, "fetch_messages", fake_fetch_messages)

    resp = await _get("/conversations/conv-1/messages")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["content"] == "hi"


# --- PATCH /conversations/{id} ---


async def test_rename_conversation_requires_auth(monkeypatch):
    _mock_verified_user(monkeypatch, None)

    resp = await _patch("/conversations/conv-1", json={"title": "New title"})

    assert resp.status_code == 401


async def test_rename_conversation_404_when_not_found(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")

    async def fake_rename(conversation_id, user_id, title):
        return False

    monkeypatch.setattr(db, "rename_conversation", fake_rename)

    resp = await _patch("/conversations/conv-1", json={"title": "New title"})

    assert resp.status_code == 404


async def test_rename_conversation_success(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")
    now = datetime.now(UTC)

    async def fake_rename(conversation_id, user_id, title):
        assert title == "New title"
        return True

    async def fake_fetch_conversation(conversation_id, user_id):
        return {"id": "conv-1", "title": "New title", "surface": "chat", "created_at": now, "updated_at": now}

    monkeypatch.setattr(db, "rename_conversation", fake_rename)
    monkeypatch.setattr(db, "fetch_conversation", fake_fetch_conversation)

    resp = await _patch("/conversations/conv-1", json={"title": "New title"})

    assert resp.status_code == 200
    assert resp.json()["title"] == "New title"


# --- DELETE /conversations/{id} ---


async def test_delete_conversation_requires_auth(monkeypatch):
    _mock_verified_user(monkeypatch, None)

    resp = await _delete("/conversations/conv-1")

    assert resp.status_code == 401


async def test_delete_conversation_404_when_not_owned(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")
    touched = []

    async def not_owned(conversation_id, user_id):
        return None

    async def record_delete_memes(memes):
        touched.append("storage")

    async def record_delete(conversation_id, user_id):
        touched.append("db")
        return True

    monkeypatch.setattr(db, "fetch_conversation_memes", not_owned)
    monkeypatch.setattr(storage, "delete_memes", record_delete_memes)
    monkeypatch.setattr(db, "delete_conversation", record_delete)

    resp = await _delete("/conversations/not-mine")

    assert resp.status_code == 404
    assert touched == []  # nothing is removed for a conversation the caller does not own


async def test_delete_conversation_removes_images_before_rows(monkeypatch):
    _mock_verified_user(monkeypatch, "user-1")
    order = []

    async def fake_fetch_memes(conversation_id, user_id):
        assert (conversation_id, user_id) == ("conv-1", "user-1")
        return [("abc1234567", "https://pub.example/abc1234567.png")]

    async def fake_delete_memes(memes):
        order.append(("storage", memes))

    async def fake_delete(conversation_id, user_id):
        order.append(("db", conversation_id, user_id))
        return True

    monkeypatch.setattr(db, "fetch_conversation_memes", fake_fetch_memes)
    monkeypatch.setattr(storage, "delete_memes", fake_delete_memes)
    monkeypatch.setattr(db, "delete_conversation", fake_delete)

    resp = await _delete("/conversations/conv-1")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert order == [
        ("storage", [("abc1234567", "https://pub.example/abc1234567.png")]),
        ("db", "conv-1", "user-1"),
    ]


async def test_delete_conversation_reports_a_storage_failure_and_keeps_the_rows(monkeypatch):
    """If the images cannot be removed, the rows that say where they are
    must survive so a retry can find them, and the caller must be told."""
    _mock_verified_user(monkeypatch, "user-1")
    db_deletes = []

    async def fake_fetch_memes(conversation_id, user_id):
        return [("abc1234567", "https://pub.example/abc1234567.png")]

    async def failing_delete_memes(memes):
        raise storage.MemeDeleteError("1 stored image(s) could not be removed")

    async def fake_delete(conversation_id, user_id):
        db_deletes.append(conversation_id)
        return True

    monkeypatch.setattr(db, "fetch_conversation_memes", fake_fetch_memes)
    monkeypatch.setattr(storage, "delete_memes", failing_delete_memes)
    monkeypatch.setattr(db, "delete_conversation", fake_delete)

    resp = await _delete("/conversations/conv-1")

    assert resp.status_code == 500
    assert "couldn't delete" in resp.json()["detail"]
    assert db_deletes == []
