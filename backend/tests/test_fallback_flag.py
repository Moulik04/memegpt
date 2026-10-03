"""The chat `done` event says whether the router fell back to the canned meme.

A fallback meme is a valid-looking 200, so without this flag nothing outside
the process (a deploy smoke test, a scheduled probe) can tell a working router
from one that has quietly stopped routing.
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from nlp.intent_router import FALLBACK_REASONING_PREFIX, is_fallback
from schemas import IntentResponse


def _intent(reasoning: str | None) -> IntentResponse:
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={"public_face": "everything is fine", "inner_reality": "it is not"},
        reasoning=reasoning,
    )


def test_is_fallback_matches_the_hard_fallback_reasoning():
    assert is_fallback(_intent(f"{FALLBACK_REASONING_PREFIX} model failed to produce valid JSON"))


def test_is_fallback_is_false_for_a_real_pick_even_on_the_fallback_template():
    assert not is_fallback(_intent("the situation is quiet panic behind a smile"))
    assert not is_fallback(_intent(None))


def _done_events(raw_text: str) -> list[dict]:
    events = [json.loads(line[len("data: "):]) for line in raw_text.splitlines() if line.startswith("data: ")]
    return [e for e in events if e.get("type") == "done"]


@pytest.mark.parametrize(
    "reasoning, expected",
    [
        (f"{FALLBACK_REASONING_PREFIX} timed out before producing a result", True),
        ("a genuine router explanation", False),
    ],
)
async def test_done_event_carries_the_fallback_flag(monkeypatch, reasoning, expected):
    async def fake_parse_intent(user_message, *args, **kwargs):
        return _intent(reasoning)

    monkeypatch.setattr("routers.chat.parse_intent", fake_parse_intent)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat/", json={"message": "waiting for my PR to get reviewed"})

    done = _done_events(resp.text)
    assert len(done) == 1
    assert done[0]["fallback"] is expected
