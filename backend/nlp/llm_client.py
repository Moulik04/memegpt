"""
Shared LLM dispatch — extracted from intent_router.py (pure refactor, no
behavior change) so the new segmentation step (nlp/segmentation.py) can
reuse the same Groq/Ollama call + retry + JSON-cleanup logic that's already
been hardened this session (the Qwen <think>-token fix, the 429
retry-after cap) without duplicating ~80 lines of it.

Both intent_router.py's parse_intent() and segmentation.py's
segment_contexts() are the same shape of task — plain text in, JSON out —
so they share this dispatcher rather than segmentation.py restricting
itself to Groq/Anthropic the way nlp/vision.py does (vision.py's
Groq/Anthropic-only choice is specifically because the local Ollama model
has no vision capability; that constraint doesn't apply to a text-only call).
"""

from __future__ import annotations

import asyncio
import re

import httpx

import circuit_breaker

# Groq's rate limits are per-model (confirmed live against their docs —
# separate RPM/RPD/TPM/TPD per model, not one shared account-wide pool),
# so this is keyed by model name — tripping qwen's circuit must never
# affect gpt-oss's independent one. 60s is a conservative per-minute-window
# guess (Groq doesn't publish an exact reset cadence per model the way
# Gemini's docs do).
_GROQ_CIRCUIT_COOLDOWN_SECONDS = 60.0


async def call_ollama(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_predict": 150},
    }
    try:
        base = settings.ollama_host.rstrip("/")
        response = await client.post(
            f"{base}/api/chat",
            json=payload,
            headers={"ngrok-skip-browser-warning": "true"},
            follow_redirects=True,
            timeout=120.0,
        )
        response.raise_for_status()
    except httpx.ConnectError:
        raise httpx.ConnectError(
            f"Cannot reach Ollama at {settings.ollama_host}. Run: ollama serve"
        )
    return response.json()["message"]["content"].strip()


async def call_groq(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    """Groq cloud inference — free tier, ~400 t/s, no GPU required."""
    for attempt in range(2):
        payload: dict = {
            "model": settings.groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }
        # Qwen 3.x thinking mode emits reasoning tokens before JSON, breaking the parser.
        # Disable it explicitly for any Qwen model on this endpoint.
        if "qwen" in settings.groq_model.lower():
            payload["reasoning_effort"] = "none"
        # gpt-oss models don't support "none" (400s: must be low/medium/high) and,
        # left unset, spend the whole max_tokens budget on hidden reasoning before
        # ever emitting content — the response comes back empty. "low" leaves
        # enough of the 200-token budget for the actual JSON.
        elif "gpt-oss" in settings.groq_model.lower():
            payload["reasoning_effort"] = "low"
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        if response.status_code == 429:
            # Rate limited — respect Groq's retry-after (cap at 30s so we don't stall forever)
            retry_after = int(response.headers.get("retry-after", "3"))
            await asyncio.sleep(min(retry_after, 8))
            continue
        response.raise_for_status()
        circuit_breaker.reset(f"groq:{settings.groq_model}")
        return response.json()["choices"][0]["message"]["content"].strip()
    # Both attempts hit 429 — return empty so the caller falls through to its
    # own hard fallback rather than raising httpx.HTTPStatusError and
    # bypassing that fallback entirely. Also trip this model's circuit so
    # a caller with multiple models to try (intent_router.py's secondary-
    # model fallback) can skip straight past a model it already knows is
    # currently rate-limited on a subsequent request.
    circuit_breaker.trip(f"groq:{settings.groq_model}", _GROQ_CIRCUIT_COOLDOWN_SECONDS)
    return ""


async def call_llm(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    """Route to Groq (cloud) or Ollama (local) based on LLM_PROVIDER config."""
    if settings.llm_provider == "groq" and settings.groq_api_key:
        return await call_groq(client, settings, messages, temperature)
    return await call_ollama(client, settings, messages, temperature)


def strip_markdown(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    return raw.strip()
