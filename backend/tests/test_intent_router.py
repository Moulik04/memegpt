"""
nlp/intent_router.py's parse_intent() must never hang indefinitely — a
pathological run (429s on both the primary and retry attempts, each
internally retrying once inside call_groq()) was observed compounding past
90s in production with zero events reaching the caller. This covers the
outer asyncio.wait_for boundary added to guarantee a bounded fallback.
"""

from __future__ import annotations

import asyncio

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
