"""
The "plan" SSE event (Lore mode Phase 2) — _stream_batch() announces the
resolved situations up front, but only when there's more than one; "plan
theater" for a single meme is pointless regardless of whether that single
situation came from the zero-LLM fast path or segmentation itself.
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


async def test_multi_situation_request_emits_plan_event_before_thinking(monkeypatch):
    async def fake_call_llm(client, settings, messages, temperature=0.75):
        return '{"contexts": [{"situation": "first thing"}, {"situation": "second thing"}]}'

    monkeypatch.setattr("nlp.segmentation.call_llm", fake_call_llm)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/chat/", json={"message": "a very long message " * 20}
        )

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    plan_events = [e for e in events if e.get("type") == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["total"] == 2
    assert plan_events[0]["situations"] == ["first thing", "second thing"]

    # The plan event must be the very first event in the stream.
    assert events[0]["type"] == "plan"


async def test_short_single_message_emits_no_plan_event():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat/", json={"message": "waiting for my PR to get reviewed"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    plan_events = [e for e in events if e.get("type") == "plan"]
    assert len(plan_events) == 0
