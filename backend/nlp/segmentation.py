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

Every entry it returns is a distinct moment unless its take_of says
otherwise. A moment is never repeated to reach a requested count: exact and
reworded duplicates are dropped, the model is asked once more for whatever
is still missing, and only then are the remaining slots filled with entries
explicitly marked as another take on a moment already in the list.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

import httpx

from config import get_settings
from nlp.llm_client import call_llm, strip_markdown
from schemas import SegmentedContext

_OVERALL_TIMEOUT_SECONDS = 45.0

# A moment is 1-2 sentences, roughly 30-50 tokens. llm_client's default
# output cap is sized for one meme's captions and a list of moments does not
# fit in it: the reply comes back as valid JSON cut off after three or four
# moments, and the ones from the end of the input are silently lost.
_OUTPUT_TOKENS_BASE = 100
_OUTPUT_TOKENS_PER_MOMENT = 120

# Picking out moments is extraction, not writing. At llm_client's default
# temperature the model, told the user wants five memes, now and then
# stretched a two-moment paste to four by retelling a moment in new words.
# Measured on the production model: at this setting that did not happen,
# and pastes with five real moments still came back as five.
_SEGMENTATION_TEMPERATURE = 0.3

_SEGMENTATION_SYSTEM_PROMPT = """\
You split a message (and/or photo descriptions) into distinct meme-worthy
moments. Identify between 1 and {max_count} SEPARATE situations — genuinely
different moments, topics, or punchlines, not just different sentences
about the same thing. Never describe the same moment twice, whether in
different words or from a second angle. Equally, never join two unrelated
events into one situation just because the same person mentions them back
to back: each gets its own. If the whole input is really just one
situation, return exactly one. Phrase each situation in 1-2 casual
first-person sentences, exactly as if the user were describing that one
moment themselves in a chat message (e.g. "my dog destroyed the couch again"
or "stuck in traffic for the third hour and everyone in the car is losing it").
{count_instruction}
{lexicon_instruction}
Respond with ONLY valid JSON, no markdown, no explanation:
{{"contexts": [{{"situation": "..."}}]}}\
"""

_COUNT_INSTRUCTION_TEMPLATE = (
    "The user asked for {n} memes. Return up to {n} contexts, strongest "
    "first. Never repeat or reword a moment to reach {n}: if the input has "
    "fewer than {n} genuinely distinct moments, return only the ones that "
    "exist."
)

# The second request, sent only when an explicit count came up short. The
# moments already found travel in the user message next to the input (see
# _build_more_material), not in this prompt: they are derived from what the
# user pasted, and user-derived text stays out of the instruction channel.
#
# Worded to expect an empty answer, and sent at a low temperature. Asked
# plainly for "N more", the model obliges even when there are none, by
# retelling a found moment in fresh vocabulary — exactly the repeat that the
# word-overlap check below cannot see.
_MORE_SYSTEM_PROMPT = """\
A first pass over a message (and/or photo descriptions) already picked out
the moments listed under "Already found". Check whether it missed any.
Usually it did not, and the right answer is then an empty list.

Return a moment only if it is about something none of the found moments
mention at all: a separate event with its own part of the input that no
found moment draws on. Do NOT return a found moment reworded, a detail,
consequence or reaction that belongs to one, or a summary that combines
several. Return at most {n}.

Phrase each one in 1-2 casual first-person sentences, exactly as if the user
were describing that one moment themselves in a chat message.
{lexicon_instruction}
Respond with ONLY valid JSON, no markdown, no explanation:
{{"contexts": [{{"situation": "..."}}]}}\
"""
_MORE_TEMPERATURE = 0.2

_LEXICON_INSTRUCTION_TEMPLATE = (
    "This group's recurring names/running jokes, for context only, not "
    "something every situation needs to reference: {lexicon}."
)

# --- Near-duplicate detection -------------------------------------------
#
# Word overlap between two situations, after dropping filler words and
# trimming common endings. Thresholds were set from real output of the
# production model: the same moment reworded scored 0.11-0.69 overlap
# (median 0.25) and 0.21-0.92 containment, while different moments from the
# same paste never scored above 0.14 and 0.30. The cut sits above the
# highest "different" score, so it favors keeping a real moment over
# removing a repeat. It does not catch the same beat told in entirely
# different words; the prompts above are what keep that from happening.
_NEAR_DUPLICATE_OVERLAP = 0.25
_NEAR_DUPLICATE_CONTAINMENT = 0.4
# Below this many shared words the ratios are noise: two short moments about
# the same person ("sam lost the key" / "sam lost the bet") are not repeats.
_NEAR_DUPLICATE_MIN_SHARED_WORDS = 4

_FILLER_WORDS = frozenset(
    """a an the and or but so because of to in on at for from with by is am are was were be been
    being i i'm im i've ive i'll me my mine we our you your he he's she they them his her its it
    it's this that these those not no just very really literally absolutely completely genuinely
    actually even still also now right has have had do does did can can't could will would should
    about into out up over like as if while when then than too all any some more most every there
    here what who how which""".split()
)
_WORD_ENDINGS = ("ing", "ed", "es", "s")


def _content_words(situation: str) -> frozenset[str]:
    words = set()
    for word in re.findall(r"[a-z0-9']+", situation.lower()):
        word = word.strip("'")
        if word.endswith("'s"):
            word = word[:-2]
        if word in _FILLER_WORDS or len(word) < 3:
            continue
        for ending in _WORD_ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                word = word[: -len(ending)]
                break
        words.add(word)
    return frozenset(words)


def _is_near_duplicate(a: str, b: str) -> bool:
    if " ".join(a.lower().split()) == " ".join(b.lower().split()):
        return True
    words_a, words_b = _content_words(a), _content_words(b)
    shared = len(words_a & words_b)
    if shared < _NEAR_DUPLICATE_MIN_SHARED_WORDS:
        return False
    overlap = shared / len(words_a | words_b)
    containment = shared / min(len(words_a), len(words_b))
    return overlap >= _NEAR_DUPLICATE_OVERLAP or containment >= _NEAR_DUPLICATE_CONTAINMENT


def _drop_near_duplicates(situations: list[str]) -> list[str]:
    """Keeps the first of every group of exact or reworded repeats, in
    order — the model lists the strongest moments first."""
    kept: list[str] = []
    for situation in situations:
        if situation.strip() and not any(_is_near_duplicate(situation, k) for k in kept):
            kept.append(situation)
    return kept


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


def _build_more_material(material: str, found: list[str]) -> str:
    """The same input, followed by the moments the first request already
    produced, for the second request to steer clear of."""
    listed = "\n".join(f"{i}. {situation}" for i, situation in enumerate(found, 1))
    return f"{material}\n\nAlready found:\n{listed}"


async def _ask_for_moments(
    system_prompt: str, material: str, max_tokens: int, deadline: float, temperature: float = 0.75
) -> list[str] | None:
    """One model call. Returns the situations it named (possibly none), or
    None if the call failed or there was no time left to make it."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        try:
            raw = await asyncio.wait_for(
                call_llm(client, settings, [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": material},
                ], temperature=temperature, max_tokens=max_tokens),
                timeout=remaining,
            )
            data = json.loads(strip_markdown(raw))
            return [SegmentedContext(**c).situation for c in data["contexts"]]
        except Exception:
            # Broad on purpose — segment_contexts must NEVER raise to the
            # caller (same "never raises" invariant as parse_intent), so any
            # failure mode (network, malformed JSON, an unexpected bug, or a
            # timeout from the asyncio.wait_for above) degrades the same way
            # rather than hanging or bringing down the whole request.
            return None


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

    With an explicit requested_count the result has exactly that many
    entries whenever the model answered at all: distinct moments first, then
    (only if a second request still left it short) entries with take_of set.
    Both requests share one _OVERALL_TIMEOUT_SECONDS budget, so asking twice
    never makes the caller wait longer than asking once could.

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
    max_tokens = _OUTPUT_TOKENS_BASE + _OUTPUT_TOKENS_PER_MOMENT * max_count
    deadline = time.monotonic() + _OVERALL_TIMEOUT_SECONDS

    found = await _ask_for_moments(
        system_prompt, material, max_tokens, deadline, temperature=_SEGMENTATION_TEMPERATURE
    )
    moments = _drop_near_duplicates(found or [])[: clamped_count or max_count]
    if not moments:
        return fallback

    if clamped_count is not None and len(moments) < clamped_count:
        more_prompt = _MORE_SYSTEM_PROMPT.format(
            n=clamped_count - len(moments),
            lexicon_instruction=lexicon_instruction,
        )
        more = await _ask_for_moments(
            more_prompt, _build_more_material(material, moments), max_tokens, deadline,
            temperature=_MORE_TEMPERATURE,
        )
        if more:
            moments = _drop_near_duplicates(moments + more)[:clamped_count]

    contexts = [SegmentedContext(situation=moment) for moment in moments]
    if clamped_count is not None:
        # Still short: the input simply has fewer distinct moments than were
        # asked for. Fill the rest with further takes, starting from the
        # strongest moment and moving down the list so no single moment
        # carries every extra.
        for extra in range(clamped_count - len(moments)):
            source = extra % len(moments)
            contexts.append(SegmentedContext(situation=moments[source], take_of=source))

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
) -> list[SegmentedContext]:
    """Returns one entry per meme to generate. The only function other
    modules should call."""
    image_descriptions = image_descriptions or []

    if not _should_segment(text, len(image_descriptions), requested_count):
        if len(image_descriptions) == 1 and not text:
            situation = image_descriptions[0]
        elif len(image_descriptions) == 1 and text:
            situation = f"{image_descriptions[0]} {text.strip()}"
        elif not image_descriptions:
            situation = text or ""
        else:
            situation = _combine_raw(text, image_descriptions)
        return [SegmentedContext(situation=situation)]

    return await segment_contexts(text, image_descriptions, requested_count, lexicon)
