"""
Content moderation for uploaded images — Phase 0 safety gate, step 4.

Uses the same already-verified vision-capable Groq model as nlp/vision.py
(qwen/qwen3.6-27b) with a strict safety-classification rubric, rather than
a dedicated Llama-Guard-style moderation model: Llama Guard's exact
request/response contract on Groq hasn't been verified against a live
call, and shipping code against an unverified API contract risks silently
failing OPEN if the parsed response format doesn't match reality — worse
than not having a dedicated model at all. Reusing the general vision model
is verified-workable (identical call shape to nlp/vision.py's own
describe_image() calls) and is a standard fallback pattern: use a general
vision model with a strict safety rubric when a dedicated moderation
model's contract isn't confirmed. Swapping in meta-llama/llama-guard-4-12b
later is a one-function change (_moderate_groq below) once its real
output format is verified against a live key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

import telemetry
from config import get_settings
from nlp.vision import call_groq_vision

logger = logging.getLogger(__name__)

_MODERATION_SYSTEM_PROMPT = (
    "You are a strict content-safety classifier for a public meme-generation "
    "app. Respond with EXACTLY one line, nothing else: either\n"
    "SAFE\n"
    "or\n"
    "UNSAFE: <category>\n"
    "where <category> is exactly one of: sexual, minors, violence, hate.\n"
    "Block any image containing sexual or explicit content, any "
    "sexualization of minors, graphic violence or gore, or hate symbols or "
    "hateful imagery. Err on the side of caution — if genuinely unsure, "
    "respond UNSAFE: unclear rather than SAFE."
)


@dataclass
class ModerationResult:
    passed: bool
    category: str | None = None


async def moderate_image(image: Image.Image) -> ModerationResult:
    """Every uploaded image must pass this before any further processing.
    Fails CLOSED (rejects) on any provider error or missing configuration —
    an inability to run the check is treated the same as a failed check,
    never as a silent pass-through."""
    settings = get_settings()
    if not settings.groq_api_key:
        logger.warning("moderation_not_configured")
        result = ModerationResult(passed=False, category="moderation_unavailable")
    else:
        try:
            result = await _moderate_groq(image, settings)
        except Exception:
            logger.warning("moderation_provider_error")
            result = ModerationResult(passed=False, category="moderation_unavailable")
    if not result.passed:
        telemetry.record_moderation_rejection(result.category or "unspecified")
    return result


async def _moderate_groq(image: Image.Image, settings) -> ModerationResult:
    raw = await call_groq_vision(
        image,
        _MODERATION_SYSTEM_PROMPT,
        "Classify this image.",
        settings.moderation_model,
        settings,
        max_tokens=20,
        temperature=0,
    )
    text = raw.strip().lower()
    if text.startswith("safe"):
        return ModerationResult(passed=True)
    if "unsafe" in text:
        category = text.split(":", 1)[1].strip() if ":" in text else "unspecified"
        return ModerationResult(passed=False, category=category)
    # Unparseable response — fail closed rather than guess.
    logger.warning("moderation_unparseable_response")
    return ModerationResult(passed=False, category="unparseable_response")
