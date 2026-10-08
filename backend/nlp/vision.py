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
Groq is primary — settings.vision_model, the SAME model intent_router.py already
uses for text routing, so this needs zero new provider account or API key.
It's currently the ONLY vision-capable model on Groq's API (groq/compound,
groq/compound-mini, and llama-3.3-70b-versatile are all text-only, and
meta-llama/llama-4-maverick/-scout both 404), so there is no
same-provider fallback to add today; Anthropic
(claude-sonnet-5) remains the only fallback tier, gated on
ANTHROPIC_API_KEY being configured, called via raw httpx to match this
repo's existing style (no SDK — intent_router.py's Groq/Ollama calls are
both raw httpx too).

call_groq_vision() is also reused by uploads/moderation.py for the content-
safety check, since that's the same kind of call (image in, short
classification text out) against the same already-verified vision model.

A rate-limit response is waited out and retried inside call_groq_vision(),
so all three photo calls get the same patience. When the retries run out
the caller is told it was a rate limit (VisionRateLimited / VisionBusy)
rather than a generic failure, so the user can be asked to try again
shortly instead of being told their photo was the problem.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import random

import httpx
from PIL import Image

from config import Settings, get_settings
from nlp.llm_client import daily_limit_active, daily_limit_cooldown, mark_daily_limit
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

# Rate-limit patience for one photo call. Each photo costs two calls of
# about 1.9k tokens on a model whose budget is per minute and shared with
# the router: measured with photos sent 12 seconds apart, 4 of 9 uploads hit
# a 429. Groq's retry-after says when the budget frees up, so that is what
# gets waited, a few times over. The budget caps the waiting for one call,
# because the person is watching a spinner: past it they are told to try
# again in a minute, which is about how long the limit's window is anyway.
# A photo is two calls, so its worst case is twice the budget.
_RATE_LIMIT_ATTEMPTS = 4
_RATE_LIMIT_WAIT_BUDGET_SECONDS = 45.0
_RATE_LIMIT_FALLBACK_WAIT_SECONDS = 2.0  # doubles per attempt when Groq sends no retry-after
_RATE_LIMIT_JITTER_SECONDS = 1.0  # photos in one upload are called together, and would retry together


class VisionRateLimited(Exception):
    """Groq answered 429 until call_groq_vision()'s retries ran out."""


class VisionDailyLimited(VisionRateLimited):
    """The 429 was Groq's daily cap, not the per-minute one, or the model was
    already known to be out for the day. Nothing is waited on or retried."""


class VisionUnavailable(Exception):
    """Raised when no configured vision provider could produce a
    description. Unlike parse_intent(), there is no safe hardcoded fallback
    description here — the caller must handle degrading to asking the user
    to describe the image in words."""


class VisionBusy(VisionUnavailable):
    """VisionUnavailable because of a rate limit that outlasted the retries.
    Trying the same photo again shortly is likely to work, so the caller
    says that instead of asking for a description in words."""


class VisionOutOfBudget(VisionBusy):
    """VisionBusy where the limit is the daily one. Trying again in a minute
    will not work, so the caller says the day's budget is used up."""


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Groq's retry-after header, in seconds (whole or decimal). None when
    it is missing or unreadable."""
    try:
        seconds = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


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
    plain-text calls are unaffected.

    A 429 is waited out and retried (see _RATE_LIMIT_ATTEMPTS above), for
    as long as Groq's retry-after asks. Raises VisionRateLimited once the
    attempts or the wait budget are used up. Nothing else is retried.

    The daily cap is the exception (see nlp/llm_client.py): it raises
    VisionDailyLimited on the first 429, and while the model is known to be
    out for the day the photo is not sent at all."""
    if daily_limit_active(model):
        raise VisionDailyLimited("the model is out of its daily budget")
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
    waited = 0.0
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt in range(_RATE_LIMIT_ATTEMPTS):
            resp = await client.post(_GROQ_CHAT_URL, json=payload, headers=headers)
            if resp.status_code != 429:
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            daily_cooldown = daily_limit_cooldown(resp)
            if daily_cooldown is not None:
                mark_daily_limit(model, daily_cooldown)
                logger.warning("vision_daily_limit", extra={"cooldown_seconds": round(daily_cooldown)})
                raise VisionDailyLimited("the model is out of its daily budget")
            if attempt == _RATE_LIMIT_ATTEMPTS - 1:
                break
            wait = _retry_after_seconds(resp)
            if wait is None:
                wait = _RATE_LIMIT_FALLBACK_WAIT_SECONDS * 2**attempt
            wait += random.uniform(0, _RATE_LIMIT_JITTER_SECONDS)
            if waited + wait > _RATE_LIMIT_WAIT_BUDGET_SECONDS:
                # Sleeping through a wait the budget cannot cover would only
                # delay the same answer.
                break
            await asyncio.sleep(wait)
            waited += wait
    logger.warning("vision_rate_limited", extra={"waited_seconds": round(waited, 1)})
    raise VisionRateLimited(f"still rate limited after waiting {waited:.0f}s")


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
    configured. Raises VisionUnavailable if every configured provider fails,
    as VisionBusy when what stopped Groq was a rate limit, and as
    VisionOutOfBudget when that limit was the daily one."""
    settings = get_settings()

    raw: str | None = None
    rate_limited = out_of_budget = False
    try:
        raw = await _describe_groq(image, user_text, settings)
    except Exception as exc:
        rate_limited = isinstance(exc, VisionRateLimited)
        out_of_budget = isinstance(exc, VisionDailyLimited)
        logger.warning("vision_provider_error", extra={"provider": "groq"})
        if settings.anthropic_api_key:
            try:
                raw = await _describe_anthropic(image, user_text, settings)
            except Exception:
                logger.warning("vision_provider_error", extra={"provider": "anthropic"})

    if not raw:
        if out_of_budget:
            raise VisionOutOfBudget("the vision provider is out of its daily budget")
        if rate_limited:
            raise VisionBusy("the vision provider is rate limited")
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
    lossy paraphrase, and it's half the latency/cost. Returns None on a
    failure of the call or its output (network, malformed JSON, missing
    keys). The one thing it raises is VisionBusy, when a rate limit outlasted
    the retries: that photo is worth sending again in a minute, which None
    could not say. On the daily cap it is the VisionOutOfBudget kind."""
    settings = get_settings()

    raw: str | None = None
    rate_limited = out_of_budget = False
    try:
        raw = await _caption_groq(image, user_text, settings)
    except Exception as exc:
        rate_limited = isinstance(exc, VisionRateLimited)
        out_of_budget = isinstance(exc, VisionDailyLimited)
        logger.warning("canvas_caption_provider_error", extra={"provider": "groq"})
        if settings.anthropic_api_key:
            try:
                raw = await _caption_anthropic(image, user_text, settings)
            except Exception:
                logger.warning("canvas_caption_provider_error", extra={"provider": "anthropic"})

    if not raw:
        if out_of_budget:
            raise VisionOutOfBudget("the vision provider is out of its daily budget")
        if rate_limited:
            raise VisionBusy("the vision provider is rate limited")
        return None

    try:
        data = json.loads(raw)
        top_text = str(data["top_text"])
        bottom_text = str(data["bottom_text"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("canvas_caption_unparseable_response")
        return None

    return {"top_text": top_text, "bottom_text": bottom_text}
