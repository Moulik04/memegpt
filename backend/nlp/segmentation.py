"""
Multi-context segmentation — identifies 1..N distinct meme-worthy moments in
a long text dump and/or multiple photo descriptions, so one submission can
produce several memes instead of being flattened into a single one.

Pure text-in/JSON-out, the same shape of task as intent_router.py's
parse_intent() — reuses llm_client.py's Groq/Ollama dispatch rather than
restricting itself to vision-capable providers the way nlp/vision.py does,
since by the time this runs, any images have already been converted to
plain-text descriptions by describe_image().

resolve_contexts() owns the trigger policy and is the only function other
modules should call: it skips the segmentation LLM call entirely for the
common case (one short message, or one photo with no explicit multi-meme
request), reproducing today's exact single-context behavior with zero
added latency or cost.
"""

from __future__ import annotations

import asyncio
import json

import httpx
from pydantic import ValidationError

from config import get_settings
from nlp.llm_client import call_llm, strip_markdown
from schemas import SegmentedContext

_OVERALL_TIMEOUT_SECONDS = 45.0

_SEGMENTATION_SYSTEM_PROMPT = """\
You split a message (and/or photo descriptions) into distinct meme-worthy
moments. Identify between 1 and {max_count} SEPARATE situations — genuinely
different moments, topics, or punchlines, not just different sentences
about the same thing. If the whole input is really just one situation,
return exactly one. Phrase each situation in 1-2 casual first-person
sentences, exactly as if the user were describing that one moment
themselves in a chat message (e.g. "my dog destroyed the couch again" or
"stuck in traffic for the third hour and everyone in the car is losing it").
{count_instruction}
{lexicon_instruction}
Respond with ONLY valid JSON, no markdown, no explanation:
{{"contexts": [{{"situation": "..."}}]}}\
"""

_COUNT_INSTRUCTION_TEMPLATE = (
    "The user explicitly asked for exactly {n} memes — return EXACTLY {n} "
    "contexts. If fewer than {n} genuinely distinct moments exist, split "
    "the dominant one into different angles to reach {n}."
)

_LEXICON_INSTRUCTION_TEMPLATE = (
    "This group's recurring names/running jokes, for context only, not "
    "something every situation needs to reference: {lexicon}."
)


def _combine_raw(text: str | None, image_descriptions: list[str]) -> str:
    """Plain concatenation — used for the fast path when it must still
    handle more than one piece of input (requested_count == 1 forces the
    fast path even over multiple images or long text), and as the hard
    fallback when the segmentation LLM call fails entirely. No LLM
    involved here, so this is mechanical, not smart segmentation."""
    parts = list(image_descriptions)
    if text:
        parts.append(text.strip())
    return " ".join(parts)


def _build_material(text: str | None, image_descriptions: list[str]) -> str:
    """Labeled, multi-line material fed to the segmentation LLM call —
    distinct from _combine_raw, which produces a single situation string."""
    parts = []
    if text:
        parts.append(f"Message:\n{text}")
    for i, desc in enumerate(image_descriptions, 1):
        parts.append(f"Photo {i}: {desc}")
    return "\n\n".join(parts)


async def segment_contexts(
    text: str | None,
    image_descriptions: list[str] | None = None,
    requested_count: int | None = None,
    lexicon: list[str] | None = None,
) -> list[SegmentedContext]:
    """Identify 1..max_memes_per_request distinct meme-worthy moments.
    Never raises — hard-falls-back to a single context (the plain
    concatenation of all input) if the LLM call fails entirely, matching
    the pre-segmentation single-context behavior.

    lexicon (Growth Phase C, optional): this anon user's opt-in Lore
    lexicon — reaches this prompt only through the instruction channel
    below, never through _build_material's content channel."""
    settings = get_settings()
    image_descriptions = image_descriptions or []
    max_count = settings.max_memes_per_request
    material = _build_material(text, image_descriptions)
    fallback = [SegmentedContext(situation=_combine_raw(text, image_descriptions))]

    clamped_count = None
    count_instruction = ""
    if requested_count is not None:
        clamped_count = max(1, min(requested_count, max_count))
        count_instruction = _COUNT_INSTRUCTION_TEMPLATE.format(n=clamped_count)

    lexicon_instruction = ""
    if lexicon:
        lexicon_instruction = _LEXICON_INSTRUCTION_TEMPLATE.format(lexicon=", ".join(lexicon))

    system_prompt = _SEGMENTATION_SYSTEM_PROMPT.format(
        max_count=max_count,
        count_instruction=count_instruction,
        lexicon_instruction=lexicon_instruction,
    )

    contexts: list[SegmentedContext] = []
    async with httpx.AsyncClient() as client:
        try:
            raw = await asyncio.wait_for(
                call_llm(client, settings, [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": material},
                ]),
                timeout=_OVERALL_TIMEOUT_SECONDS,
            )
            raw = strip_markdown(raw)
            data = json.loads(raw)
            contexts = [SegmentedContext(**c) for c in data["contexts"]]
            if not contexts:
                return fallback
        except Exception:
            # Broad on purpose — this function must NEVER raise to the
            # caller (same "never raises" invariant as parse_intent), so any
            # failure mode (network, malformed JSON, an unexpected bug, or a
            # timeout from the asyncio.wait_for above) all degrade to the
            # same single-context fallback rather than hanging or bringing
            # down the whole request.
            return fallback

    contexts = contexts[:max_count]
    if clamped_count is not None:
        # Pad by repeating the strongest (first) context — parse_intent's
        # existing avoid_templates mechanism naturally diversifies repeats,
        # since each context is run through _stream_chat_turn in sequence
        # and add_turn() runs after each one before the next is parsed.
        while len(contexts) < clamped_count:
            contexts.append(contexts[0])
        contexts = contexts[:clamped_count]

    return contexts


def _should_segment(text: str | None, image_count: int, requested_count: int | None) -> bool:
    """Owns the trigger policy. False = fast path, zero LLM calls — a
    normal short message or a single photo with no explicit multi-meme ask."""
    settings = get_settings()
    if requested_count is not None:
        return requested_count > 1
    if image_count >= 2:
        return True
    if text is not None and len(text) >= settings.segmentation_text_threshold_chars:
        return True
    return False


async def resolve_contexts(
    text: str | None,
    image_descriptions: list[str] | None = None,
    requested_count: int | None = None,
    lexicon: list[str] | None = None,
) -> list[str]:
    """Returns a plain list of situation strings, one per meme to generate.
    The only function other modules should call."""
    image_descriptions = image_descriptions or []

    if not _should_segment(text, len(image_descriptions), requested_count):
        if len(image_descriptions) == 1 and not text:
            return [image_descriptions[0]]
        if len(image_descriptions) == 1 and text:
            return [f"{image_descriptions[0]} {text.strip()}"]
        if not image_descriptions:
            return [text or ""]
        return [_combine_raw(text, image_descriptions)]

    contexts = await segment_contexts(text, image_descriptions, requested_count, lexicon)
    return [c.situation for c in contexts]
