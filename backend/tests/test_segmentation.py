"""
nlp/segmentation.py — the trigger policy (resolve_contexts) must skip the
segmentation LLM call entirely for the common case, and segment_contexts
must degrade to a single combined context if the LLM call fails.
"""

from __future__ import annotations

import asyncio

import nlp.segmentation as segmentation
from nlp.segmentation import resolve_contexts, segment_contexts
from schemas import SegmentedContext


async def _never_called(*args, **kwargs):
    raise AssertionError("call_llm should not have been invoked on the fast path")


async def test_short_text_takes_fast_path_zero_llm_calls(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    result = await resolve_contexts("waiting for my PR to get reviewed", None, None)
    assert result == ["waiting for my PR to get reviewed"]


async def test_single_image_no_text_fast_path(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    result = await resolve_contexts(None, ["a dog destroying a couch"], None)
    assert result == ["a dog destroying a couch"]


async def test_single_image_with_text_fast_path_merges(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    result = await resolve_contexts("lol", ["a dog destroying a couch"], None)
    assert result == ["a dog destroying a couch lol"]


async def test_requested_count_one_forces_fast_path_even_on_long_text(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    long_text = "this is a very long message. " * 20
    result = await resolve_contexts(long_text, None, 1)
    assert len(result) == 1


async def test_long_text_invokes_segmentation(monkeypatch):
    called = {}

    async def fake_call_llm(client, settings, messages, temperature=0.75):
        called["invoked"] = True
        return '{"contexts": [{"situation": "first thing"}, {"situation": "second thing"}]}'

    monkeypatch.setattr("nlp.segmentation.call_llm", fake_call_llm)
    long_text = "this is a very long message. " * 20
    result = await resolve_contexts(long_text, None, None)

    assert called.get("invoked") is True
    assert result == ["first thing", "second thing"]


async def test_segmentation_llm_failure_falls_back_to_one_context(monkeypatch):
    async def failing_call_llm(client, settings, messages, temperature=0.75):
        raise RuntimeError("network exploded")

    monkeypatch.setattr("nlp.segmentation.call_llm", failing_call_llm)
    long_text = "this is a very long message. " * 20
    result = await resolve_contexts(long_text, None, None)

    # Never raises — degrades to exactly one context (today's pre-segmentation behavior)
    assert len(result) == 1
    assert long_text.strip() in result[0]


async def test_segmentation_malformed_json_falls_back(monkeypatch):
    async def bad_json_call_llm(client, settings, messages, temperature=0.75):
        return "not valid json at all"

    monkeypatch.setattr("nlp.segmentation.call_llm", bad_json_call_llm)
    contexts = await segment_contexts("some long text " * 20, None, None)
    assert len(contexts) == 1
    assert isinstance(contexts[0], SegmentedContext)


async def test_segmentation_call_hanging_past_the_ceiling_falls_back(monkeypatch):
    """A pathological hang (e.g. compounding 429 backoff) must degrade to
    the same single-context fallback within a bounded time, not stall the
    request indefinitely — see nlp/intent_router.py's parse_intent for the
    matching fix and the bug this was modeled on."""
    monkeypatch.setattr(segmentation, "_OVERALL_TIMEOUT_SECONDS", 0.05)

    async def hanging_call_llm(client, settings, messages, temperature=0.75):
        await asyncio.sleep(10)
        return '{"contexts": [{"situation": "should never get here"}]}'

    monkeypatch.setattr(segmentation, "call_llm", hanging_call_llm)
    long_text = "this is a very long message. " * 20

    result = await asyncio.wait_for(resolve_contexts(long_text, None, None), timeout=2.0)

    assert len(result) == 1
    assert long_text.strip() in result[0]


async def test_requested_count_pads_by_repeating_dominant_context(monkeypatch):
    async def fake_call_llm(client, settings, messages, temperature=0.75):
        return '{"contexts": [{"situation": "only one real moment"}]}'

    monkeypatch.setattr("nlp.segmentation.call_llm", fake_call_llm)
    result = await resolve_contexts("a message " * 40, None, 3)
    assert len(result) == 3
    assert all(s == "only one real moment" for s in result)
