"""
nlp/segmentation.py — the trigger policy (resolve_contexts) must skip the
segmentation LLM call entirely for the common case, and segment_contexts
must degrade to a single combined context if the LLM call fails.
"""

from __future__ import annotations

import asyncio
import json

import nlp.segmentation as segmentation
from nlp.segmentation import resolve_contexts, segment_contexts
from schemas import SegmentedContext


def _situations(contexts: list[SegmentedContext]) -> list[str]:
    return [c.situation for c in contexts]


def _scripted_llm(*replies: str):
    """A call_llm stand-in that returns each reply in turn and records the
    messages and output budget of every call it received."""
    calls: list[dict] = []
    pending = list(replies)

    async def fake_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        calls.append({"messages": messages, "max_tokens": max_tokens, "temperature": temperature})
        return pending.pop(0)

    return fake_call_llm, calls


def _contexts_json(*situations: str) -> str:
    return json.dumps({"contexts": [{"situation": s} for s in situations]})


_KEY_HUNT = "I checked the front desk, the kitchen drawer and even inside the microwave for the mail room key"
_KEY_HOSTAGE = "Sam has the key I need for an urgent package and refuses to hand it over until Monday"
_ALBUM_HYPE = "I am on the hype train for the new Drake album and convinced the song is called Nitrous"
_HEARD_LIVE = "I already heard the track live at the show and cannot wait another second for the official release"
_PARKING = "My roommate parked across two spaces again and left a note blaming the car next to him"
_LONG_PASTE = "a message " * 40


async def _never_called(*args, **kwargs):
    raise AssertionError("call_llm should not have been invoked on the fast path")


async def test_short_text_takes_fast_path_zero_llm_calls(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    result = await resolve_contexts("waiting for my PR to get reviewed", None, None)
    assert _situations(result) == ["waiting for my PR to get reviewed"]


async def test_single_image_no_text_fast_path(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    result = await resolve_contexts(None, ["a dog destroying a couch"], None)
    assert _situations(result) == ["a dog destroying a couch"]


async def test_single_image_with_text_fast_path_merges(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    result = await resolve_contexts("lol", ["a dog destroying a couch"], None)
    assert _situations(result) == ["a dog destroying a couch lol"]


async def test_requested_count_one_forces_fast_path_even_on_long_text(monkeypatch):
    monkeypatch.setattr("nlp.segmentation.call_llm", _never_called)
    long_text = "this is a very long message. " * 20
    result = await resolve_contexts(long_text, None, 1)
    assert len(result) == 1


async def test_long_text_invokes_segmentation(monkeypatch):
    called = {}

    async def fake_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        called["invoked"] = True
        return '{"contexts": [{"situation": "first thing"}, {"situation": "second thing"}]}'

    monkeypatch.setattr("nlp.segmentation.call_llm", fake_call_llm)
    long_text = "this is a very long message. " * 20
    result = await resolve_contexts(long_text, None, None)

    assert called.get("invoked") is True
    assert _situations(result) == ["first thing", "second thing"]


async def test_segmentation_llm_failure_falls_back_to_one_context(monkeypatch):
    async def failing_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        raise RuntimeError("network exploded")

    monkeypatch.setattr("nlp.segmentation.call_llm", failing_call_llm)
    long_text = "this is a very long message. " * 20
    result = await resolve_contexts(long_text, None, None)

    # Never raises — degrades to exactly one context (today's pre-segmentation behavior)
    assert len(result) == 1
    assert long_text.strip() in result[0].situation


async def test_segmentation_malformed_json_falls_back(monkeypatch):
    async def bad_json_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
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

    async def hanging_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        await asyncio.sleep(10)
        return '{"contexts": [{"situation": "should never get here"}]}'

    monkeypatch.setattr(segmentation, "call_llm", hanging_call_llm)
    long_text = "this is a very long message. " * 20

    result = await asyncio.wait_for(resolve_contexts(long_text, None, None), timeout=2.0)

    assert len(result) == 1
    assert long_text.strip() in result[0].situation


async def test_requested_count_never_pads_with_a_copy(monkeypatch):
    """One real moment and a count of 3: the moment appears once, and the
    other two slots are marked as further takes on it instead of being
    presented as moments of their own."""
    fake, calls = _scripted_llm(_contexts_json(_KEY_HUNT), _contexts_json())
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    result = await resolve_contexts(_LONG_PASTE, None, 3)

    assert len(result) == 3
    assert [c.take_of for c in result] == [None, 0, 0]
    assert [c.situation for c in result if c.take_of is None] == [_KEY_HUNT]


async def test_exact_and_reworded_duplicates_are_dropped(monkeypatch):
    reworded_hunt = "I checked the front desk, the kitchen drawer, and even inside the microwave looking for that mail room key"
    fake, _ = _scripted_llm(_contexts_json(_KEY_HUNT, _KEY_HOSTAGE, _KEY_HUNT, reworded_hunt, _ALBUM_HYPE))
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    contexts = await segment_contexts(_LONG_PASTE, None, None)

    assert _situations(contexts) == [_KEY_HUNT, _KEY_HOSTAGE, _ALBUM_HYPE]


async def test_distinct_moments_about_the_same_people_are_all_kept(monkeypatch):
    """The near-duplicate check must not merge different moments just
    because they share a name or an object."""
    moments = [_KEY_HUNT, _KEY_HOSTAGE, _ALBUM_HYPE, _HEARD_LIVE, _PARKING]
    fake, calls = _scripted_llm(_contexts_json(*moments))
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    result = await resolve_contexts(_LONG_PASTE, None, 5)

    assert _situations(result) == moments
    assert all(c.take_of is None for c in result)
    assert len(calls) == 1  # nothing was missing, so no second request


async def test_shortfall_asks_once_more_excluding_what_was_found(monkeypatch):
    fake, calls = _scripted_llm(
        _contexts_json(_KEY_HUNT, _KEY_HOSTAGE, _ALBUM_HYPE),
        _contexts_json(_HEARD_LIVE, _PARKING),
    )
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    result = await resolve_contexts(_LONG_PASTE, None, 5)

    assert _situations(result) == [_KEY_HUNT, _KEY_HOSTAGE, _ALBUM_HYPE, _HEARD_LIVE, _PARKING]
    assert all(c.take_of is None for c in result)
    assert len(calls) == 2
    second_request = " ".join(m["content"] for m in calls[1]["messages"])
    for found in (_KEY_HUNT, _KEY_HOSTAGE, _ALBUM_HYPE):
        assert found in second_request
    assert "at most 2" in second_request
    # Asked warmly, the model answers "any more?" by retelling a found moment.
    assert calls[1]["temperature"] < calls[0]["temperature"]


async def test_second_request_repeating_a_found_moment_adds_nothing(monkeypatch):
    fake, calls = _scripted_llm(
        _contexts_json(_KEY_HUNT, _KEY_HOSTAGE, _ALBUM_HYPE, _HEARD_LIVE),
        _contexts_json(_KEY_HUNT),
    )
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    result = await resolve_contexts(_LONG_PASTE, None, 5)

    assert len(calls) == 2
    assert _situations(result)[:4] == [_KEY_HUNT, _KEY_HOSTAGE, _ALBUM_HYPE, _HEARD_LIVE]
    assert [c.take_of for c in result] == [None, None, None, None, 0]


async def test_extra_takes_rotate_from_the_strongest_moment(monkeypatch):
    fake, _ = _scripted_llm(_contexts_json(_KEY_HUNT, _ALBUM_HYPE), _contexts_json())
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    result = await resolve_contexts(_LONG_PASTE, None, 5)

    assert [c.take_of for c in result] == [None, None, 0, 1, 0]
    assert [c.situation for c in result[2:]] == [_KEY_HUNT, _ALBUM_HYPE, _KEY_HUNT]


async def test_failed_second_request_still_never_raises(monkeypatch):
    replies = [_contexts_json(_KEY_HUNT, _KEY_HOSTAGE)]

    async def flaky_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        if replies:
            return replies.pop(0)
        raise RuntimeError("network exploded")

    monkeypatch.setattr("nlp.segmentation.call_llm", flaky_call_llm)

    result = await resolve_contexts(_LONG_PASTE, None, 3)

    assert [c.take_of for c in result] == [None, None, 0]


async def test_no_extra_takes_when_no_count_was_requested(monkeypatch):
    fake, calls = _scripted_llm(_contexts_json(_KEY_HUNT, _KEY_HOSTAGE))
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    result = await resolve_contexts(_LONG_PASTE, None, None)

    assert _situations(result) == [_KEY_HUNT, _KEY_HOSTAGE]
    assert len(calls) == 1


async def test_no_extra_takes_when_segmentation_itself_failed(monkeypatch):
    """A failed model call degrades to one meme from the whole input, not
    to several takes on an input nobody managed to read."""
    async def failing_call_llm(client, settings, messages, temperature=0.75, max_tokens=None):
        raise RuntimeError("network exploded")

    monkeypatch.setattr("nlp.segmentation.call_llm", failing_call_llm)

    result = await resolve_contexts(_LONG_PASTE, None, 5)

    assert len(result) == 1
    assert result[0].take_of is None


async def test_segmentation_asks_for_enough_output_for_a_full_list(monkeypatch):
    """llm_client's default output cap is sized for one meme's captions. A
    full list of moments does not fit in it, and a cut-off reply silently
    loses the moments from the end of the input."""
    fake, calls = _scripted_llm(_contexts_json(_KEY_HUNT, _KEY_HOSTAGE))
    monkeypatch.setattr("nlp.segmentation.call_llm", fake)

    await segment_contexts(_LONG_PASTE, None, None)

    assert calls[0]["max_tokens"] is not None
    assert calls[0]["max_tokens"] >= 500
