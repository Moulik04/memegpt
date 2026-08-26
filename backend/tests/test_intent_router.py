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

import circuit_breaker as cb
import nlp.intent_router as intent_router
from config import Settings
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
    """Groq occasionally returns a JSON array (`[{...}]`) instead of an
    object despite explicit instructions not to. _normalize_llm_response()
    used to call `.items()` unconditionally, raising an unhandled
    AttributeError that neither except clause in parse_intent() caught —
    escaping the documented "never raises to the caller" hard-fallback
    guarantee and 500-ing the request instead. A single-item array is
    unambiguous enough to unwrap and use directly, rather than discarding
    a perfectly good response just because of the wrapping."""

    async def array_call_llm(client, settings, messages, temperature=0.75):
        return '[{"template_id": "drake", "texts": {"rejected_option": "a"}}]'

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


# --- Groq secondary-model resilience follow-up ---

def _groq_settings(model="qwen/qwen3.6-27b", fallback="openai/gpt-oss-120b") -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="groq",
        groq_api_key="fake-key",
        groq_model=model,
        groq_fallback_model=fallback,
    )


async def test_fallback_model_attempt_fires_when_primary_fails_twice(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", lambda: _groq_settings())

    async def call_llm_by_model(client, settings, messages, temperature=0.75):
        if settings.groq_model == "openai/gpt-oss-120b":
            return '{"template_id": "drake", "texts": {"rejected_option": "a"}}'
        return "not valid json at all"  # primary model fails both its attempts

    monkeypatch.setattr(intent_router, "call_llm", call_llm_by_model)

    result = await parse_intent("anything")

    assert result.template_id == "drake"  # a real pick, not the hardcoded fallback


async def test_no_distinct_fallback_model_behaves_exactly_as_before(monkeypatch):
    """groq_fallback_model == groq_model (or unset) must never add a
    pointless third attempt at the same model — exact pre-existing
    2-attempt-then-hardcoded-fallback shape, unchanged."""
    monkeypatch.setattr(intent_router, "get_settings", lambda: _groq_settings(fallback=""))

    calls: list[str] = []

    async def call_llm_track(client, settings, messages, temperature=0.75):
        calls.append(settings.groq_model)
        return "not valid json"

    monkeypatch.setattr(intent_router, "call_llm", call_llm_track)

    result = await parse_intent("anything")

    assert calls == ["qwen/qwen3.6-27b", "qwen/qwen3.6-27b"]
    assert result.template_id == "hide_the_pain_harold"


async def test_open_primary_circuit_skips_straight_to_fallback_model(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", lambda: _groq_settings())
    cb.trip("groq:qwen/qwen3.6-27b", cooldown_seconds=60)

    calls: list[str] = []

    async def call_llm_track(client, settings, messages, temperature=0.75):
        calls.append(settings.groq_model)
        return '{"template_id": "drake", "texts": {"rejected_option": "a"}}'

    monkeypatch.setattr(intent_router, "call_llm", call_llm_track)

    result = await parse_intent("anything")

    assert calls == ["openai/gpt-oss-120b"]  # attempts 1+2 (primary model) never ran
    assert result.template_id == "drake"


async def test_all_three_attempts_failing_still_reaches_hard_fallback(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", lambda: _groq_settings())

    calls: list[str] = []

    async def call_llm_always_bad(client, settings, messages, temperature=0.75):
        calls.append(settings.groq_model)
        return "not valid json"

    monkeypatch.setattr(intent_router, "call_llm", call_llm_always_bad)

    result = await parse_intent("anything")

    assert calls == ["qwen/qwen3.6-27b", "qwen/qwen3.6-27b", "openai/gpt-oss-120b"]
    assert result.template_id == "hide_the_pain_harold"


# --- Blank-caption bug: retry-path responses whose texts don't match any
# real box label for the resolved template must not be accepted as success.
# Root cause: _RETRY_TEMPLATE's example JSON shows a literal "BOX_LABEL"
# placeholder key and never lists the resolved template's real box labels
# (unlike the rich first-attempt system prompt, which does) — so whenever
# generation falls through to the retry path, the model either echoes back
# "BOX_LABEL" literally or guesses a plausible name in the wrong case
# (e.g. "BUTTON_1" instead of "button_1"). compose_meme()'s exact-match
# `texts.get(box_cfg.label, "")` lookup then finds nothing for every real
# box and silently renders a blank meme — no error anywhere in the pipeline.

async def test_texts_matching_no_real_box_label_is_not_accepted(monkeypatch):
    """Reproduces the actual observed failure: a real template_id with a
    texts dict keyed by the literal 'BOX_LABEL' placeholder (which matches
    no real box label for two_buttons) must be treated as a failed attempt,
    not returned as a successful result that would render blank."""
    monkeypatch.setattr(intent_router, "get_settings", lambda: _groq_settings(fallback=""))

    async def call_llm_placeholder_key(client, settings, messages, temperature=0.75):
        return '{"template_id": "two_buttons", "texts": {"BOX_LABEL": "some caption"}, "reasoning": "x"}'

    monkeypatch.setattr(intent_router, "call_llm", call_llm_placeholder_key)

    result = await parse_intent("adding things to my cart and never checking out")

    assert result.template_id == "hide_the_pain_harold"
    assert "Fallback" in result.reasoning


async def test_case_mismatched_real_labels_are_salvaged_not_discarded(monkeypatch):
    """Unlike the placeholder-key case above, BUTTON_1/BUTTON_2 are real
    content just in the wrong case — worth normalizing back onto the
    template's actual button_1/button_2 labels rather than throwing away a
    perfectly good caption and re-rolling."""
    monkeypatch.setattr(intent_router, "get_settings", lambda: _groq_settings(fallback=""))

    async def call_llm_wrong_case(client, settings, messages, temperature=0.75):
        return (
            '{"template_id": "two_buttons", '
            '"texts": {"BUTTON_1": "Add to cart", "BUTTON_2": "Checkout"}, '
            '"reasoning": "x"}'
        )

    monkeypatch.setattr(intent_router, "call_llm", call_llm_wrong_case)

    result = await parse_intent("adding things to my cart and never checking out")

    assert result.template_id == "two_buttons"
    assert result.texts == {"button_1": "Add to cart", "button_2": "Checkout"}


async def test_normalize_texts_to_box_labels_matches_case_insensitively():
    from nlp.intent_router import _normalize_texts_to_box_labels

    result = _normalize_texts_to_box_labels(
        {"BUTTON_1": "a", "BUTTON_2": "b"}, "two_buttons"
    )
    assert result == {"button_1": "a", "button_2": "b"}


async def test_normalize_texts_to_box_labels_drops_unmatched_keys():
    from nlp.intent_router import _normalize_texts_to_box_labels

    result = _normalize_texts_to_box_labels({"BOX_LABEL": "some caption"}, "two_buttons")
    assert result == {}


async def test_normalize_texts_to_box_labels_ignores_blank_values():
    from nlp.intent_router import _normalize_texts_to_box_labels

    result = _normalize_texts_to_box_labels(
        {"button_1": "  ", "button_2": "real caption"}, "two_buttons"
    )
    assert result == {"button_2": "real caption"}


async def test_retry_prompt_includes_real_box_labels_for_available_templates():
    """The actual root cause: the retry-path prompt used to list only
    template_ids, never each one's real box labels, unlike the rich
    first-attempt prompt — leaving a model that reaches this path with no
    way to know the correct keys."""
    from nlp.intent_router import _build_retry_prompt

    prompt = _build_retry_prompt("anything", ["two_buttons", "drake"])

    assert "button_1" in prompt
    assert "button_2" in prompt
    assert "rejected_option" in prompt
    assert "approved_option" in prompt
