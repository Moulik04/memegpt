"""
intent_parse_failures_total (by stage), hard_fallback_hits_total, and
moderation_rejections_total (by category) must fire on every real
occurrence of the failure mode they name. Reuses this suite's existing
fixture patterns: intent_router tests monkeypatch call_llm the same way
test_intent_router.py already does; moderation tests monkeypatch at the
settings/network boundary the same way test_generate_moderation.py and
test_text_moderation.py already do.
"""

from __future__ import annotations

import nlp.intent_router as intent_router
import telemetry
import uploads.moderation as image_moderation
from config import Settings
from nlp.intent_router import parse_intent
from nlp.text_moderation import moderate_text
from uploads.moderation import moderate_image


def _groq_settings(model="qwen/qwen3.6-27b", fallback="openai/gpt-oss-120b") -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="groq",
        groq_api_key="fake-key",
        groq_model=model,
        groq_fallback_model=fallback,
    )


async def test_all_three_attempts_failing_records_each_stage_and_one_hard_fallback(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", lambda: _groq_settings())

    async def call_llm_always_bad(client, settings, messages, temperature=0.75):
        return "not valid json"

    monkeypatch.setattr(intent_router, "call_llm", call_llm_always_bad)

    stage_calls = []
    fallback_calls = []
    monkeypatch.setattr(telemetry, "record_intent_parse_failure", lambda stage: stage_calls.append(stage))
    monkeypatch.setattr(telemetry, "record_hard_fallback_hit", lambda: fallback_calls.append(1))

    result = await parse_intent("anything")

    assert stage_calls == ["primary", "retry", "fallback_model"]
    assert fallback_calls == [1]
    assert result.template_id == "hide_the_pain_harold"


async def test_timeout_records_exactly_one_hard_fallback(monkeypatch):
    monkeypatch.setattr(intent_router, "_OVERALL_TIMEOUT_SECONDS", 0.05)

    async def hanging_call_llm(client, settings, messages, temperature=0.75):
        import asyncio

        await asyncio.sleep(10)
        return "{}"

    monkeypatch.setattr(intent_router, "call_llm", hanging_call_llm)

    fallback_calls = []
    monkeypatch.setattr(telemetry, "record_hard_fallback_hit", lambda: fallback_calls.append(1))

    result = await parse_intent("anything")

    assert fallback_calls == [1]
    assert result.template_id == "hide_the_pain_harold"


async def test_image_moderation_rejection_is_recorded_with_its_category(monkeypatch):
    async def fake_moderate_groq(image, settings):
        from uploads.moderation import ModerationResult

        return ModerationResult(passed=False, category="violence")

    monkeypatch.setattr(image_moderation, "_moderate_groq", fake_moderate_groq)
    monkeypatch.setattr(image_moderation, "get_settings", lambda: _groq_settings())

    rejection_calls = []
    monkeypatch.setattr(telemetry, "record_moderation_rejection", lambda category: rejection_calls.append(category))

    from PIL import Image

    result = await moderate_image(Image.new("RGB", (10, 10)))

    assert result.passed is False
    assert rejection_calls == ["violence"]


async def test_image_moderation_pass_records_nothing(monkeypatch):
    async def fake_moderate_groq(image, settings):
        from uploads.moderation import ModerationResult

        return ModerationResult(passed=True)

    monkeypatch.setattr(image_moderation, "_moderate_groq", fake_moderate_groq)
    monkeypatch.setattr(image_moderation, "get_settings", lambda: _groq_settings())

    rejection_calls = []
    monkeypatch.setattr(telemetry, "record_moderation_rejection", lambda category: rejection_calls.append(category))

    from PIL import Image

    result = await moderate_image(Image.new("RGB", (10, 10)))

    assert result.passed is True
    assert rejection_calls == []


async def test_text_moderation_rejection_is_recorded_with_its_category(monkeypatch):
    rejection_calls = []
    monkeypatch.setattr(telemetry, "record_moderation_rejection", lambda category: rejection_calls.append(category))

    # No GROQ_API_KEY in the test environment (conftest.py isolates .env) —
    # moderate_text fails closed with category="moderation_unavailable".
    result = await moderate_text("some caption")

    assert result.passed is False
    assert rejection_calls == ["moderation_unavailable"]


async def test_text_moderation_blank_text_records_nothing(monkeypatch):
    rejection_calls = []
    monkeypatch.setattr(telemetry, "record_moderation_rejection", lambda category: rejection_calls.append(category))

    result = await moderate_text("   ")

    assert result.passed is True
    assert rejection_calls == []
