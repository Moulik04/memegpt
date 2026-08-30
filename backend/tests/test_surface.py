"""
Growth Phase D — the Chat/Lore endpoint split. Both surfaces share one
streaming core, but the endpoint that served a meme stamps a distinct
`surface` ("chat"/"lore") onto its db.insert_meme call, which is what makes
Arc's Chat-vs-Lore split real. These tests prove the stamp differs by
endpoint, without a real LLM, renderer, or database.
"""

from __future__ import annotations

import json

from httpx import ASGITransport, AsyncClient

import db
from main import app
from nlp.text_moderation import ModerationResult
from schemas import IntentResponse
from storage import SavedMeme


async def _fake_parse_intent(user_message, avoid_templates=None, loved_templates=None, hated_templates=None, lexicon=None):
    return IntentResponse(template_id="drake", texts={"top_text": "a", "bottom_text": "b"}, reasoning="stub")


async def _fake_compose_meme(template_id, texts):
    return SavedMeme(meme_id="stubmeme01", url="/static/generated/stubmeme01.png", path=None)


async def _capture_surface(monkeypatch):
    calls = []

    async def fake_insert_meme(meme_id, url, template_id, mode, anon_user_id=None, surface=None, user_id=None):
        calls.append(surface)

    monkeypatch.setattr("routers.chat.parse_intent", _fake_parse_intent)
    monkeypatch.setattr("routers.chat.compose_meme", _fake_compose_meme)
    monkeypatch.setattr(db, "insert_meme", fake_insert_meme)
    return calls


async def _post(path: str, body: dict) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(path, json=body)
    assert resp.status_code == 200
    # Drain the SSE stream so the generator (and its insert_meme call) runs.
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            json.loads(line[len("data: "):])


async def test_chat_endpoint_stamps_surface_chat(monkeypatch):
    calls = await _capture_surface(monkeypatch)
    await _post("/chat/", {"message": "hi"})
    assert calls == ["chat"]


async def test_lore_endpoint_stamps_surface_lore(monkeypatch):
    calls = await _capture_surface(monkeypatch)
    await _post("/lore/", {"message": "hi"})
    assert calls == ["lore"]


async def test_generate_endpoint_stamps_surface_make_and_identity(monkeypatch):
    """Make's manual picker used to call compose_meme() and stop — no
    db.insert_meme() call at all, so a Make-generated meme was never tied
    to any user and was invisible to Arc's stats or "Forget me". Proves
    the fix: surface="make", mode="make", and the anon id from the request
    header all reach db.insert_meme."""
    calls: list[dict] = []

    async def fake_insert_meme(meme_id, url, template_id, mode, anon_user_id=None, surface=None, user_id=None):
        calls.append({
            "mode": mode,
            "surface": surface,
            "anon_user_id": anon_user_id,
            "user_id": user_id,
        })

    async def fake_moderate_text(text):
        return ModerationResult(passed=True)

    monkeypatch.setattr("routers.generate.compose_meme", _fake_compose_meme)
    monkeypatch.setattr("routers.generate.moderate_text", fake_moderate_text)
    monkeypatch.setattr(db, "insert_meme", fake_insert_meme)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/generate/",
            json={"template_id": "drake", "texts": {"top_text": "a", "bottom_text": "b"}},
            headers={"X-MemeGPT-User": "anon-test-id"},
        )
    assert resp.status_code == 200
    assert calls == [{"mode": "make", "surface": "make", "anon_user_id": "anon-test-id", "user_id": None}]
