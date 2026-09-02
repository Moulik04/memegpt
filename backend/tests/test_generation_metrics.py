"""
meme_generation_duration_seconds and template_selection_total must fire on
every real meme generation, across all three surfaces that actually
produce one: Chat/Lore (both flow through chat.py's shared
_render_and_record_turn) and Make (routers/generate.py's direct path).
Canvas mode (_stream_canvas_turn) deliberately has no template_id — it's
excluded from template_selection_total by design, matching how
log_usage() already skips it — but still gets a duration recording,
covered separately if canvas mode is exercised in a later phase; not in
scope here since the design spec's metrics table only names the
context-mode (Mode 1) + Make paths.
"""

from __future__ import annotations

import telemetry
from schemas import IntentResponse
from storage import SavedMeme


async def test_render_and_record_turn_records_duration_and_template(monkeypatch):
    import routers.chat as chat_router

    async def fake_compose_meme(template_id, texts):
        return SavedMeme(meme_id="m1", url="http://example.com/m1.png", path=None)

    monkeypatch.setattr(chat_router, "compose_meme", fake_compose_meme)
    monkeypatch.setattr(chat_router, "add_turn", lambda *a, **k: None)
    monkeypatch.setattr(chat_router, "log_usage", lambda *a, **k: None)

    duration_calls = []
    template_calls = []
    monkeypatch.setattr(telemetry, "record_meme_generation", lambda surface, duration: duration_calls.append((surface, duration)))
    monkeypatch.setattr(telemetry, "record_template_selection", lambda template_id: template_calls.append(template_id))

    intent = IntentResponse(template_id="drake", texts={"top_text": "a", "bottom_text": "b"}, reasoning="test")
    await chat_router._render_and_record_turn(intent, "hello", "conv-1", surface="lore")

    assert len(duration_calls) == 1
    surface, duration = duration_calls[0]
    assert surface == "lore"
    assert duration >= 0
    assert template_calls == ["drake"]


async def test_generate_endpoint_records_duration_and_template_for_make(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    import routers.generate as generate_router
    from main import app
    from nlp.text_moderation import ModerationResult
    from storage import SavedMeme

    async def fake_moderate_text(text):
        return ModerationResult(passed=True)

    async def fake_compose_meme(template_id, texts):
        return SavedMeme(meme_id="m2", url="http://example.com/m2.png", path=None)

    monkeypatch.setattr(generate_router, "moderate_text", fake_moderate_text)
    monkeypatch.setattr(generate_router, "compose_meme", fake_compose_meme)

    duration_calls = []
    template_calls = []
    monkeypatch.setattr(telemetry, "record_meme_generation", lambda surface, duration: duration_calls.append((surface, duration)))
    monkeypatch.setattr(telemetry, "record_template_selection", lambda template_id: template_calls.append(template_id))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/generate/",
            json={"template_id": "drake", "texts": {"rejected_option": "a", "approved_option": "b"}},
        )

    assert resp.status_code == 200
    assert duration_calls == [("make", duration_calls[0][1])]
    assert template_calls == ["drake"]
