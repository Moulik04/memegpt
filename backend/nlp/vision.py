"""
Vision layer — Phase 1 (Mode 1: image as context) + Phase 2 (Mode 2: canvas).

describe_image() describes an already-safety-checked image in plain
language, phrased as if the user had typed it, so it can feed straight into
the EXISTING parse_intent() unchanged (Mode 1). generate_canvas_captions()
instead asks the vision model directly for top/bottom meme captions on the
photo itself (Mode 2) — one call, not describe-then-caption in two, since
the caption writer benefits from seeing the actual pixels rather than a
lossy paraphrase, and it's half the latency/cost.

Mirrors nlp/llm_client.py's call_groq/call_ollama dispatch shape (this
module has its own Groq/Anthropic vision-specific callers below, separate
from llm_client.py, since llm_client.py's callers are text-only):
Groq is primary — qwen/qwen3.6-27b, the SAME model intent_router.py already
uses for text routing, so this needs zero new provider account or API key.
It's currently the ONLY vision-capable model on Groq's API (verified live —
groq/compound, groq/compound-mini, and llama-3.3-70b-versatile are all
text-only, and meta-llama/llama-4-maverick/-scout both 404 as of this
writing), so there is no same-provider fallback to add today; Anthropic
(claude-sonnet-5) remains the only fallback tier, gated on
ANTHROPIC_API_KEY being configured, called via raw httpx to match this
repo's existing style (no SDK — intent_router.py's Groq/Ollama calls are
both raw httpx too).

call_groq_vision() is also reused by uploads/moderation.py for the content-
safety check, since that's the same kind of call (image in, short
classification text out) against the same already-verified vision model.
"""

from __future__ import annotations

import base64
import io
import json
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

_CANVAS_CAPTION_SYSTEM_PROMPT = (
    "You write classic meme captions directly onto this photo — the photo "
    "itself IS the meme template, top text and bottom text, Impact-font "
    "style. Look at the scene, the mood, and anything funny or ironic about "
    "it, and write a short top_text and bottom_text pair that turns it into "
    "a meme. If the photo already has visible text/writing baked into it, "
    "do NOT repeat or recaption that text — write new captions instead. "
    "Keep each caption under 60 characters.\n\n"
    'Respond with ONLY valid JSON, no markdown, no explanation: '
    '{"top_text": "...", "bottom_text": "..."}'
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
    response_format: dict | None = None,
) -> str:
    """Low-level Groq vision chat-completion call, shared by describe_image(),
    generate_canvas_captions() below, and uploads/moderation.py. Raises on
    any HTTP/parsing failure — callers decide how to degrade. Never logs the
    image bytes or the response content at info level (only warnings on
    failure, message-free). `response_format` is only included in the
    payload when the caller passes it (e.g. {"type": "json_object"} for
    generate_canvas_captions) — describe_image()'s and moderate_image()'s
    plain-text calls are unaffected."""
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
    if response_format is not None:
        payload["response_format"] = response_format
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


def infer_mode(user_text: str | None) -> str:
    """Cheap deterministic keyword check — no LLM call. Computed ONCE per
    request in routers/chat.py from the shared message text (not per image —
    every image in a batch shares the same accompanying text, so a
    per-image hint would always be redundant)."""
    if not user_text:
        return "context"
    lowered = user_text.lower()
    if any(phrase in lowered for phrase in _CANVAS_PHRASES):
        return "canvas"
    return "context"


async def describe_image(image: Image.Image, user_text: str | None = None) -> VisionDescription:
    """Provider-agnostic vision description (Mode 1: image as context).
    Tries Groq first, falls back to Anthropic if ANTHROPIC_API_KEY is
    configured. Raises VisionUnavailable if every configured provider fails."""
    settings = get_settings()

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

    return VisionDescription(situation=raw)


async def _caption_groq(image: Image.Image, user_text: str | None, settings: Settings) -> str:
    prompt = user_text or "Write meme captions for this photo."
    return await call_groq_vision(
        image,
        _CANVAS_CAPTION_SYSTEM_PROMPT,
        prompt,
        settings.vision_model,
        settings,
        response_format={"type": "json_object"},
    )


async def _caption_anthropic(image: Image.Image, user_text: str | None, settings: Settings) -> str:
    b64 = _encode_for_api(image)
    payload = {
        "model": settings.anthropic_model,
        "max_tokens": 200,
        "thinking": {"type": "disabled"},
        "system": _CANVAS_CAPTION_SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": user_text or "Write meme captions for this photo."},
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


async def generate_canvas_captions(image: Image.Image, user_text: str | None = None) -> dict[str, str] | None:
    """Mode 2 (canvas): one vision call asking directly for top/bottom meme
    captions on the photo itself, rather than a separate describe-then-
    caption round trip — the caption writer sees the actual pixels, not a
    lossy paraphrase, and it's half the latency/cost. Returns None on ANY
    failure (network, malformed JSON, missing keys) — never raises, so a
    caller gathering several of these can just filter out the Nones rather
    than needing return_exceptions=True."""
    settings = get_settings()

    raw: str | None = None
    try:
        raw = await _caption_groq(image, user_text, settings)
    except Exception:
        logger.warning("canvas_caption_provider_error", extra={"provider": "groq"})
        if settings.anthropic_api_key:
            try:
                raw = await _caption_anthropic(image, user_text, settings)
            except Exception:
                logger.warning("canvas_caption_provider_error", extra={"provider": "anthropic"})

    if not raw:
        return None

    try:
        data = json.loads(raw)
        top_text = str(data["top_text"])
        bottom_text = str(data["bottom_text"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("canvas_caption_unparseable_response")
        return None

    return {"top_text": top_text, "bottom_text": bottom_text}
