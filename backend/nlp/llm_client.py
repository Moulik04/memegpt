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
        return response.json()["choices"][0]["message"]["content"].strip()
    # Both attempts hit 429 — return empty so the caller falls through to its
    # own hard fallback rather than raising httpx.HTTPStatusError and
    # bypassing that fallback entirely
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
