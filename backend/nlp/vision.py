"""
Vision layer — Phase 1 (Mode 1: image as context).

Describes an already-safety-checked image (a safe_ingest.CleanImage's
.image) in plain language, phrased as if the user had typed it, so it can
feed straight into the EXISTING parse_intent() unchanged.

Mirrors nlp/llm_client.py's call_groq/call_ollama dispatch shape (this
module has its own Groq/Anthropic vision-specific callers below, separate
from llm_client.py, since llm_client.py's callers are text-only):
Groq is primary — qwen/qwen3.6-27b, the SAME model intent_router.py already
uses for text routing, so this needs zero new provider account or API key.
Anthropic (claude-sonnet-5) is an optional fallback if ANTHROPIC_API_KEY is
configured, called via raw httpx to match this repo's existing style (no
SDK — intent_router.py's Groq/Ollama calls are both raw httpx too).

call_groq_vision() is also reused by uploads/moderation.py for the content-
safety check, since that's the same kind of call (image in, short
classification text out) against the same already-verified vision model.
"""

from __future__ import annotations

import base64
import io
import logging

import httpx
from PIL import Image

from config import Settings, get_settings
from schemas import VisionDescription

logger = logging.getLogger(__name__)

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"

_VISION_SYSTEM_PROMPT = (
    "You describe photos for a meme-caption generator. In 1-3 short "
    "sentences, describe the situation/scene, the emotional tone, and any "
    "text visible in the image. Phrase it as if the user were casually "
    "describing their own photo in a chat message — first person is fine, "
    "e.g. 'my dog destroyed the couch again' or 'stuck in traffic for the "
    "third hour and everyone in the car is losing it'. Do not mention that "
    "you are an AI or that this is an image description — just describe it "
    "naturally."
)

_CANVAS_PHRASES = ("make this a meme", "meme this", "meme-ify", "meme ify", "turn this into a meme")


class VisionUnavailable(Exception):
    """Raised when no configured vision provider could produce a
    description. Unlike parse_intent(), there is no safe hardcoded fallback
    description here — the caller must handle degrading to asking the user
    to describe the image in words."""


def _encode_for_api(image: Image.Image, max_side: int = 1568, quality: int = 85) -> str:
    """Downsize + JPEG-encode + base64 a COPY of the image for inline API
    payloads. Groq's inline base64 image limit is ~4MB while uploads are
    allowed up to 10MB, so this always runs regardless of the original
    size. Never mutates the caller's image — Phase 2's canvas renderer
    needs the full-resolution original."""
    thumb = image.copy()
    thumb.thumbnail((max_side, max_side))
    if thumb.mode not in ("RGB", "L"):
        thumb = thumb.convert("RGB")
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


async def call_groq_vision(
    image: Image.Image,
    system_prompt: str,
    user_text: str,
    model: str,
    settings: Settings,
    max_tokens: int = 200,
    temperature: float = 0.4,
) -> str:
    """Low-level Groq vision chat-completion call, shared by describe_image()
    below and uploads/moderation.py. Raises on any HTTP/parsing failure —
    callers decide how to degrade. Never logs the image bytes or the
    response content at info level (only warnings on failure, message-free)."""
    b64 = _encode_for_api(image)
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if "qwen" in model.lower():
        payload["reasoning_effort"] = "none"

    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_GROQ_CHAT_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


async def _describe_groq(image: Image.Image, user_text: str | None, settings: Settings) -> str:
    prompt = user_text or "Describe this photo."
    return await call_groq_vision(image, _VISION_SYSTEM_PROMPT, prompt, settings.vision_model, settings)


async def _describe_anthropic(image: Image.Image, user_text: str | None, settings: Settings) -> str:
    b64 = _encode_for_api(image)
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 200,
        "thinking": {"type": "disabled"},
        "system": _VISION_SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": user_text or "Describe this photo."},
                ],
            }
        ],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_ANTHROPIC_MESSAGES_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["content"][0]["text"].strip()


def _infer_mode(user_text: str | None) -> str:
    """Cheap deterministic keyword check — no LLM call. Phase 1 always
    executes the Mode 1 (context) path regardless of the result; the hint
    is only acted on once Phase 2 (canvas) ships."""
    if not user_text:
        return "context"
    lowered = user_text.lower()
    if any(phrase in lowered for phrase in _CANVAS_PHRASES):
        return "canvas"
    return "context"


async def describe_image(image: Image.Image, user_text: str | None = None) -> VisionDescription:
    """Provider-agnostic vision description. Tries Groq first, falls back
    to Anthropic if ANTHROPIC_API_KEY is configured. Raises
    VisionUnavailable if every configured provider fails."""
    settings = get_settings()
    mode_hint = _infer_mode(user_text)

    raw: str | None = None
    try:
        raw = await _describe_groq(image, user_text, settings)
    except Exception:
        logger.warning("vision_provider_error", extra={"provider": "groq"})
        if settings.anthropic_api_key:
            try:
                raw = await _describe_anthropic(image, user_text, settings)
            except Exception:
                logger.warning("vision_provider_error", extra={"provider": "anthropic"})

    if not raw:
        raise VisionUnavailable("no configured vision provider produced a description")

    return VisionDescription(situation=raw, mode_hint=mode_hint)
