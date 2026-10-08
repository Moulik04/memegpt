"""
Content moderation for Make's user-typed captions — the text equivalent of
uploads/moderation.py's image content-safety gate. Make (routers/generate.py)
is the one surface where caption text never passes through an LLM at all:
Chat/Lore's captions are LLM-generated (constrained by RAG'd template
selection and the intent-parsing prompt), but Make lets a user type
arbitrary words that land directly on a public, shareable meme. Same
categories, same fail-closed semantics, same plain-text SAFE/UNSAFE
response contract as the image check, using the same general vision-
capable model in text-only mode rather than a dedicated moderation model,
for the reason described in uploads/moderation.py's module docstring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

import telemetry
from config import get_settings
from nlp.llm_client import daily_limit_active, daily_limit_cooldown, mark_daily_limit

logger = logging.getLogger(__name__)

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# The check could not be run because the provider answered 429. Still a
# failed check (see moderate_text), but one the caller can describe as busy,
# or as the day's budget being used up, instead of as a refused caption.
CATEGORY_RATE_LIMITED = "rate_limited"
CATEGORY_DAILY_LIMIT = "daily_limit"

_MODERATION_SYSTEM_PROMPT = (
    "You are a strict content-safety classifier for a public meme-caption "
    "generator. Respond with EXACTLY one line, nothing else: either\n"
    "SAFE\n"
    "or\n"
    "UNSAFE: <category>\n"
    "where <category> is exactly one of: sexual, minors, violence, hate.\n"
    "Block any text containing sexual or explicit content, any "
    "sexualization of minors, threats or incitement of violence, or hate "
    "speech/slurs targeting a person or group. Err on the side of caution "
    "— if genuinely unsure, respond UNSAFE: unclear rather than SAFE."
)


@dataclass
class ModerationResult:
    passed: bool
    category: str | None = None


async def moderate_text(text: str) -> ModerationResult:
    """Every caption Make renders onto a public meme must pass this first.
    Fails CLOSED (rejects) on any provider error or missing configuration —
    an inability to run the check is treated the same as a failed check,
    never as a silent pass-through. That includes a rate-limited provider:
    the caption is rejected, with a category that says which limit it was.
    Blank/whitespace-only text is trivially safe and skips the network call
    entirely."""
    if not text.strip():
        return ModerationResult(passed=True)
    settings = get_settings()
    if not settings.groq_api_key:
        logger.warning("text_moderation_not_configured")
        result = ModerationResult(passed=False, category="moderation_unavailable")
    else:
        try:
            result = await _moderate_groq_text(text, settings)
        except Exception:
            logger.warning("text_moderation_provider_error")
            result = ModerationResult(passed=False, category="moderation_unavailable")
    if not result.passed:
        telemetry.record_moderation_rejection(result.category or "unspecified")
    return result


async def _moderate_groq_text(text: str, settings) -> ModerationResult:
    if daily_limit_active(settings.moderation_model):
        return ModerationResult(passed=False, category=CATEGORY_DAILY_LIMIT)
    payload: dict = {
        "model": settings.moderation_model,
        "messages": [
            {"role": "system", "content": _MODERATION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 20,
    }
    if "qwen" in settings.moderation_model.lower():
        payload["reasoning_effort"] = "none"

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            _GROQ_CHAT_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code == 429:
            daily_cooldown = daily_limit_cooldown(resp)
            if daily_cooldown is None:
                logger.warning("text_moderation_rate_limited")
                return ModerationResult(passed=False, category=CATEGORY_RATE_LIMITED)
            mark_daily_limit(settings.moderation_model, daily_cooldown)
            logger.warning("text_moderation_daily_limit")
            return ModerationResult(passed=False, category=CATEGORY_DAILY_LIMIT)
        resp.raise_for_status()
        data = resp.json()

    raw = data["choices"][0]["message"]["content"].strip().lower()
    if raw.startswith("safe"):
        return ModerationResult(passed=True)
    if "unsafe" in raw:
        category = raw.split(":", 1)[1].strip() if ":" in raw else "unspecified"
        return ModerationResult(passed=False, category=category)
    logger.warning("text_moderation_unparseable_response")
    return ModerationResult(passed=False, category="unparseable_response")
