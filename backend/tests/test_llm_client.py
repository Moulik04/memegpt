"""
nlp/llm_client.py's call_groq() — the circuit-breaker trip/reset behavior
added as part of the Groq resilience follow-up (see test_intent_router.py
for the secondary-model fallback this enables). Uses httpx.MockTransport
(a real httpx testing utility, no new dependency) to construct a real
AsyncClient against canned responses — no real network call.
"""

from __future__ import annotations

import httpx

import circuit_breaker as cb
from config import Settings
from nlp.llm_client import call_groq


def _client_always_429() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "0"}, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client_always_ok() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(model: str = "qwen/qwen3.6-27b") -> Settings:
    return Settings(_env_file=None, groq_api_key="fake-key", groq_model=model)


async def test_exhausting_both_attempts_trips_the_models_circuit():
    settings = _settings("qwen/qwen3.6-27b")
    async with _client_always_429() as client:
        result = await call_groq(client, settings, [{"role": "user", "content": "hi"}])

    assert result == ""
    assert cb.is_open("groq:qwen/qwen3.6-27b") is True


def test_tripping_one_model_does_not_affect_another():
    cb.trip("groq:qwen/qwen3.6-27b", cooldown_seconds=60)
    assert cb.is_open("groq:qwen/qwen3.6-27b") is True
    assert cb.is_open("groq:openai/gpt-oss-120b") is False


async def test_a_success_resets_that_models_circuit():
    cb.trip("groq:qwen/qwen3.6-27b", cooldown_seconds=60)
    settings = _settings("qwen/qwen3.6-27b")

    async with _client_always_ok() as client:
        result = await call_groq(client, settings, [{"role": "user", "content": "hi"}])

    assert result == "hello"
    assert cb.is_open("groq:qwen/qwen3.6-27b") is False
