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
from storage import SavedMeme


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
    async def fake_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
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


# --- Extra takes: an explicit count larger than the number of distinct
# moments. The plan must never print a moment twice, and a take must never
# reuse a template its moment already has.

_ONLY_MOMENT = "the only real moment in this whole paste"


def _one_moment_then_nothing_more():
    replies = [json.dumps({"contexts": [{"situation": _ONLY_MOMENT}]}), json.dumps({"contexts": []})]

    async def fake_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        return replies.pop(0)

    return fake_call_llm


async def _fake_compose_meme(template_id, texts):
    return SavedMeme(meme_id=f"stub-{template_id}", url=f"/static/generated/stub-{template_id}.png", path=None)


async def _post_lore(count: int) -> list[dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/lore/", json={"message": "a very long message " * 20, "meme_count": count})
    assert resp.status_code == 200
    return _parse_sse_events(resp.text)


async def test_extra_takes_are_labelled_and_the_moment_is_listed_once(monkeypatch):
    picks = iter(["drake", "this_is_fine", "grus_plan"])
    exclusions_seen = []

    async def fake_parse_intent(
        user_message, avoid_templates=None, loved_templates=None, hated_templates=None,
        lexicon=None, exclude_templates=None,
    ):
        exclusions_seen.append(exclude_templates)
        return IntentResponse(template_id=next(picks), texts={"top_text": "a"}, reasoning="test stub")

    monkeypatch.setattr("nlp.segmentation.call_llm", _one_moment_then_nothing_more())
    monkeypatch.setattr("routers.chat.parse_intent", fake_parse_intent)
    monkeypatch.setattr("routers.chat.compose_meme", _fake_compose_meme)

    events = await _post_lore(3)

    plan = events[0]
    assert plan["type"] == "plan"
    assert plan["total"] == 3
    assert plan["situations"] == [_ONLY_MOMENT, "Another take on moment 1", "Another take on moment 1"]
    assert plan["take_of"] == [None, 0, 0]

    # Each take is told, as a hard rule, every template the moment already has.
    assert exclusions_seen == [None, ["drake"], ["drake", "this_is_fine"]]

    done = [e for e in events if e["type"] == "done"]
    assert [e["template_used"] for e in done] == ["drake", "this_is_fine", "grus_plan"]
    assert "take_of" not in done[0]
    assert [e["take_of"] for e in done[1:]] == [0, 0]
    assert events[-1] == {"type": "batch_done", "total": 3, "succeeded": 3}


async def test_a_take_that_can_only_repeat_the_template_is_skipped(monkeypatch):
    """parse_intent's hard fallback ignores the exclusion. Rendering it would
    show the same moment on the same template twice, so the take is dropped
    and the batch reports the real number of memes made."""

    async def always_the_same_template(
        user_message, avoid_templates=None, loved_templates=None, hated_templates=None,
        lexicon=None, exclude_templates=None,
    ):
        return IntentResponse(template_id="hide_the_pain_harold", texts={"top_text": "a"}, reasoning="Fallback: stub")

    monkeypatch.setattr("nlp.segmentation.call_llm", _one_moment_then_nothing_more())
    monkeypatch.setattr("routers.chat.parse_intent", always_the_same_template)
    monkeypatch.setattr("routers.chat.compose_meme", _fake_compose_meme)

    events = await _post_lore(2)

    assert [e["index"] for e in events if e["type"] == "done"] == [0]
    skipped = [e for e in events if e["type"] == "error"]
    assert [e["index"] for e in skipped] == [1]
    assert "different template" in skipped[0]["message"]
    assert events[-1] == {"type": "batch_done", "total": 2, "succeeded": 1}


async def test_plan_without_takes_carries_no_take_marker(monkeypatch):
    async def fake_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        return '{"contexts": [{"situation": "first thing"}, {"situation": "second thing"}]}'

    monkeypatch.setattr("nlp.segmentation.call_llm", fake_call_llm)

    events = await _post_lore(2)

    assert events[0]["situations"] == ["first thing", "second thing"]
    assert "take_of" not in events[0]
