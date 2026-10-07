"""
nlp/llm_client.py's call_groq() — the circuit-breaker trip/reset behavior
added as part of the Groq resilience follow-up (see test_intent_router.py
for the secondary-model fallback this enables). Uses httpx.MockTransport
(a real httpx testing utility, no new dependency) to construct a real
AsyncClient against canned responses — no real network call.
"""

from __future__ import annotations

import json

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


# --- output budget ----------------------------------------------------------


def _client_recording_payloads(seen: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_default_output_budget_leaves_room_for_a_reasoning_model():
    """The fallback model spends part of its budget on hidden reasoning
    before it writes any JSON. Measured on the router's prompt it used
    149-194 tokens against a 200 cap, and some requests were rejected
    outright because nothing was left for the answer."""
    seen: list[dict] = []
    async with _client_recording_payloads(seen) as client:
        await call_groq(client, _settings("openai/gpt-oss-120b"), [{"role": "user", "content": "hi"}])

    assert seen[0]["max_tokens"] >= 400


async def test_a_caller_can_ask_for_its_own_output_budget():
    seen: list[dict] = []
    async with _client_recording_payloads(seen) as client:
        await call_groq(client, _settings(), [{"role": "user", "content": "hi"}], max_tokens=700)

    assert seen[0]["max_tokens"] == 700
