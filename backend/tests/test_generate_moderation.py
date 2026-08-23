"""
POST /generate/ (Make) — captions are user-typed and never pass through an
LLM, unlike Chat/Lore's, so this is the one surface where nlp.text_moderation
must gate the request before compose_meme() ever runs. Fails closed, same
invariant as the image upload gate: a moderation-unavailable result blocks
the request rather than silently passing it through.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

import routers.generate as generate_router
from main import app
from nlp.text_moderation import ModerationResult


async def _post_generate(**payload):
    body = {"template_id": "drake", "texts": {"rejected_option": "a", "approved_option": "b"}, **payload}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/generate/", json=body)


async def test_unsafe_caption_blocks_request_with_generic_message(monkeypatch):
    calls = []

    async def fake_moderate_text(text):
        calls.append(text)
        return ModerationResult(passed=False, category="hate")

    async def fake_compose_meme(**kwargs):
        raise AssertionError("compose_meme must not run when moderation rejects the request")

    monkeypatch.setattr(generate_router, "moderate_text", fake_moderate_text)
    monkeypatch.setattr(generate_router, "compose_meme", fake_compose_meme)

    resp = await _post_generate()

    assert resp.status_code == 400
    assert "hate" not in resp.text
    assert len(calls) == 1


async def test_safe_caption_allows_generation(monkeypatch):
    async def fake_moderate_text(text):
        return ModerationResult(passed=True)

    monkeypatch.setattr(generate_router, "moderate_text", fake_moderate_text)

    resp = await _post_generate()

    assert resp.status_code == 200
    assert resp.json()["template_id"] == "drake"


async def test_no_groq_key_fails_closed_by_default(monkeypatch):
    """Integration check with the real moderate_text (no mock): the test
    suite's isolated Settings has no GROQ_API_KEY, so a non-blank caption
    must be rejected rather than silently rendered."""
    async def fake_compose_meme(**kwargs):
        raise AssertionError("compose_meme must not run when moderation is unavailable")

    monkeypatch.setattr(generate_router, "compose_meme", fake_compose_meme)

    resp = await _post_generate()

    assert resp.status_code == 400


async def test_blank_captions_do_not_require_moderation_to_be_configured(monkeypatch):
    """Make's GET /generate/file/ convenience route and any blank-caption
    submission shouldn't be blocked just because Groq isn't configured —
    moderate_text already treats blank text as trivially safe."""
    resp = await _post_generate(texts={"rejected_option": "", "approved_option": ""})

    assert resp.status_code == 200
