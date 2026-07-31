"""
Phase 1's explicit requirement: adding the new /chat/image/ endpoint must
not change the existing text-only /chat/ behavior at all. This spins up the
real FastAPI app in-process (no real network, no real server) and drives it
through httpx's ASGI transport.

parse_intent is monkeypatched to a fixed response rather than exercising the
real LLM call: with no GROQ_API_KEY configured in the test environment,
llm_provider defaults to "ollama" and would otherwise try to reach a
nonexistent local Ollama host and hang on the httpx timeout, making this
slow and flaky instead of fast and deterministic.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from schemas import IntentResponse


async def _fake_parse_intent(user_message: str, avoid_templates=None, loved_templates=None, hated_templates=None, lexicon=None) -> IntentResponse:
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={"public_face": "everything is fine", "inner_reality": user_message[:50]},
        reasoning="test stub",
    )


@pytest.fixture(autouse=True)
def _stub_parse_intent(monkeypatch):
    monkeypatch.setattr("routers.chat.parse_intent", _fake_parse_intent)


def _parse_sse_events(raw_text: str) -> list[dict]:
    events = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


async def test_text_chat_streams_done_event_with_template():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat/", json={"message": "waiting for my PR to get reviewed"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    stages = [e.get("stage") for e in events if e.get("type") == "thinking"]
    assert "analyzing" in stages
    assert "rendering" in stages

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    done = done_events[0]
    assert done["template_used"] == "hide_the_pain_harold"
    assert done["message"]["meme_url"].startswith("/static/generated/")
    assert done["index"] == 0
    assert done["total"] == 1

    # Pins "the fast path is wire-identical to before, plus a trailing
    # batch_done" as an actual regression check — a short message must take
    # zero segmentation LLM calls and resolve to exactly one context.
    batch_done_events = [e for e in events if e.get("type") == "batch_done"]
    assert len(batch_done_events) == 1
    assert batch_done_events[0]["total"] == 1
    assert batch_done_events[0]["succeeded"] == 1
