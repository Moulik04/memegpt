"""
Growth Phase G (Discord half) — POST /discord/generate. This endpoint is
never called by Discord itself (see routers/discord.py's module docstring
for why); it's called by the Cloudflare Worker, authenticated by a
pre-shared secret. These tests cover the backend's half of that contract
without a real LLM, renderer, Worker, or Discord API.
"""

from __future__ import annotations

import db
from config import Settings
from httpx import ASGITransport, AsyncClient
from main import app
from schemas import IntentResponse
from storage import SavedMeme


async def _fake_parse_intent(user_message, avoid_templates=None, loved_templates=None, hated_templates=None, lexicon=None):
    return IntentResponse(template_id="drake", texts={"top_text": "a", "bottom_text": "b"}, reasoning="stub")


async def _fake_compose_meme(template_id, texts):
    return SavedMeme(meme_id="stubmeme01", url="/static/generated/stubmeme01.png", path=None)


async def _fake_insert_meme(meme_id, url, template_id, mode, anon_user_id=None, surface=None, user_id=None):
    pass


def _fake_settings(monkeypatch, **overrides):
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr("routers.discord.get_settings", lambda: settings)
    return settings


async def _post(headers: dict | None = None, body: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/discord/generate",
            json=body or {"text": "waiting for the build to finish"},
            headers=headers or {},
        )


async def test_missing_shared_secret_is_rejected(monkeypatch):
    _fake_settings(monkeypatch, discord_worker_shared_secret="correct-secret")
    resp = await _post()
    assert resp.status_code == 403


async def test_wrong_shared_secret_is_rejected(monkeypatch):
    _fake_settings(monkeypatch, discord_worker_shared_secret="correct-secret")
    resp = await _post(headers={"X-Discord-Worker-Secret": "wrong"})
    assert resp.status_code == 403


async def test_unconfigured_secret_fails_closed(monkeypatch):
    _fake_settings(monkeypatch, discord_worker_shared_secret="")
    resp = await _post(headers={"X-Discord-Worker-Secret": "anything"})
    assert resp.status_code == 503


async def test_correct_secret_returns_meme_url(monkeypatch):
    _fake_settings(monkeypatch, discord_worker_shared_secret="correct-secret")
    monkeypatch.setattr("routers.chat.parse_intent", _fake_parse_intent)
    monkeypatch.setattr("routers.chat.compose_meme", _fake_compose_meme)
    monkeypatch.setattr(db, "insert_meme", _fake_insert_meme)

    resp = await _post(headers={"X-Discord-Worker-Secret": "correct-secret"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["meme_url"] == "/static/generated/stubmeme01.png"
    assert data["template_id"] == "drake"


async def test_surface_stamped_as_discord(monkeypatch):
    _fake_settings(monkeypatch, discord_worker_shared_secret="correct-secret")
    calls = []

    async def capturing_insert_meme(meme_id, url, template_id, mode, anon_user_id=None, surface=None, user_id=None):
        calls.append(surface)

    monkeypatch.setattr("routers.chat.parse_intent", _fake_parse_intent)
    monkeypatch.setattr("routers.chat.compose_meme", _fake_compose_meme)
    monkeypatch.setattr(db, "insert_meme", capturing_insert_meme)

    await _post(headers={"X-Discord-Worker-Secret": "correct-secret"})

    assert calls == ["discord"]


async def test_generation_failure_returns_clean_500(monkeypatch):
    _fake_settings(monkeypatch, discord_worker_shared_secret="correct-secret")

    async def failing_parse_intent(*args, **kwargs):
        raise RuntimeError("some internal detail that should not leak")

    monkeypatch.setattr("routers.chat.parse_intent", failing_parse_intent)

    resp = await _post(headers={"X-Discord-Worker-Secret": "correct-secret"})

    assert resp.status_code == 500
    assert "some internal detail" not in resp.text
