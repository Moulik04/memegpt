"""
nlp/intent_router.py's parse_intent() must never hang indefinitely — a
pathological run (429s on both the primary and retry attempts, each
internally retrying once inside call_groq()) was observed compounding past
90s in production with zero events reaching the caller. This covers the
outer asyncio.wait_for boundary added to guarantee a bounded fallback.
"""

from __future__ import annotations

import asyncio

import pytest

import nlp.intent_router as intent_router
from nlp.intent_router import parse_intent


async def test_hanging_llm_call_falls_back_within_the_timeout_ceiling(monkeypatch):
    monkeypatch.setattr(intent_router, "_OVERALL_TIMEOUT_SECONDS", 0.05)

    async def hanging_call_llm(client, settings, messages, temperature=0.75):
        await asyncio.sleep(10)
        return '{"template_id": "drake", "texts": {}}'

    monkeypatch.setattr(intent_router, "call_llm", hanging_call_llm)

    result = await asyncio.wait_for(parse_intent("anything"), timeout=2.0)

    assert result.template_id == "hide_the_pain_harold"
    assert "timed out" in result.reasoning


async def test_llm_returning_a_single_item_array_is_salvaged(monkeypatch):
    """Real production incident (Growth Phase G, Discord integration):
    Groq occasionally returns a JSON array (`[{...}]`) instead of an
    object despite explicit instructions not to. _normalize_llm_response()
    used to call `.items()` unconditionally, raising an unhandled
    AttributeError that neither except clause in parse_intent() caught —
    escaping the documented "never raises to the caller" hard-fallback
    guarantee and 500-ing the request instead. A single-item array is
    unambiguous enough to unwrap and use directly, rather than discarding
    a perfectly good response just because of the wrapping."""

    async def array_call_llm(client, settings, messages, temperature=0.75):
        return '[{"template_id": "drake", "texts": {"top_text": "a"}}]'

    monkeypatch.setattr(intent_router, "call_llm", array_call_llm)

    result = await parse_intent("anything")

    assert result.template_id == "drake"


async def test_llm_returning_a_multi_item_array_falls_back_gracefully(monkeypatch):
    """Unlike the single-item case above, a multi-item array isn't
    unambiguous enough to salvage — must degrade to the hard fallback
    like any other malformed response, not raise an unhandled exception."""

    async def array_call_llm(client, settings, messages, temperature=0.75):
        return '[{"template_id": "drake"}, {"template_id": "grus_plan"}]'

    monkeypatch.setattr(intent_router, "call_llm", array_call_llm)

    result = await parse_intent("anything")

    assert result.template_id == "hide_the_pain_harold"
    assert "Fallback" in result.reasoning


async def test_normalize_llm_response_unwraps_single_item_array():
    from nlp.intent_router import _normalize_llm_response

    data = [{"template_id": "drake", "texts": {"top_text": "a"}}]
    result = _normalize_llm_response(data, {"drake"})
    assert result == {"template_id": "drake", "texts": {"top_text": "a"}}


async def test_normalize_llm_response_rejects_multi_item_array():
    from nlp.intent_router import _normalize_llm_response

    with pytest.raises(ValueError):
        _normalize_llm_response([{"a": 1}, {"b": 2}], set())
