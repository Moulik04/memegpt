"""
Growth Phase H, Stage 3 — message persistence gating in routers/chat.py.
The core invariant: db.insert_message must NEVER fire for an anonymous
request, even if a client supplies a conversation_row_id (forged, stale, or
otherwise) — persistence requires BOTH a verified user_id AND ownership of
that conversation_row_id. Uses the same parse_intent/compose_meme stubbing
precedent as test_regression_text_chat.py / test_surface.py.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

import db
from auth import VerifiedUser
from main import app
from schemas import IntentResponse
from storage import SavedMeme


async def _fake_parse_intent(user_message, avoid_templates=None, loved_templates=None, hated_templates=None, lexicon=None):
    return IntentResponse(template_id="drake", texts={"top_text": "a", "bottom_text": "b"}, reasoning="stub")


async def _fake_compose_meme(template_id, texts):
    return SavedMeme(meme_id="stubmeme01", url="/static/generated/stubmeme01.png", path=None)


@pytest.fixture(autouse=True)
def _stub_generation(monkeypatch):
    monkeypatch.setattr("routers.chat.parse_intent", _fake_parse_intent)
    monkeypatch.setattr("routers.chat.compose_meme", _fake_compose_meme)


def _drain_sse(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]


async def _post_chat(body: dict, headers: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat/", json=body, headers=headers or {})
    _drain_sse(resp.text)  # exhaust the generator so every insert_message call actually runs
    return resp


async def test_insert_message_never_called_for_fully_anonymous_request(monkeypatch):
    calls = []

    async def fake_insert_message(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(db, "insert_message", fake_insert_message)

    await _post_chat({"message": "hi", "conversation_row_id": "some-id"})

    assert calls == []


async def test_insert_message_never_called_when_conversation_row_id_is_forged(monkeypatch):
    """Signed in, but the conversation_row_id doesn't belong to this user —
    fetch_conversation_owner returning a DIFFERENT user_id must silently
    drop persistence for the whole turn, not just skip a check."""
    calls = []

    async def fake_insert_message(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(db, "insert_message", fake_insert_message)
    monkeypatch.setattr(
        "routers.chat.get_verified_user",
        lambda request: _resolved(VerifiedUser(user_id="user-1", email=None)),
    )
    monkeypatch.setattr(db, "fetch_conversation_owner", lambda conversation_id: _resolved("someone-else"))

    await _post_chat(
        {"message": "hi", "conversation_row_id": "forged-id"},
        headers={"Authorization": "Bearer whatever"},
    )

    assert calls == []


async def test_insert_message_called_for_owned_conversation(monkeypatch):
    calls = []

    async def fake_insert_message(conversation_id, role, content, meme_id=None):
        calls.append((conversation_id, role, content, meme_id))

    async def fake_set_title(conversation_id, title):
        pass

    monkeypatch.setattr(db, "insert_message", fake_insert_message)
    monkeypatch.setattr(db, "set_conversation_title_if_unset", fake_set_title)
    monkeypatch.setattr(
        "routers.chat.get_verified_user",
        lambda request: _resolved(VerifiedUser(user_id="user-1", email=None)),
    )
    monkeypatch.setattr(db, "fetch_conversation_owner", lambda conversation_id: _resolved("user-1"))

    await _post_chat(
        {"message": "hi", "conversation_row_id": "owned-id"},
        headers={"Authorization": "Bearer whatever"},
    )

    assert len(calls) == 2
    assert calls[0] == ("owned-id", "user", "hi", None)
    assert calls[1][:3] == ("owned-id", "assistant", "hi")
    assert calls[1][3] == "stubmeme01"


async def _resolved(value):
    return value
