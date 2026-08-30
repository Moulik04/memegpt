"""
Growth Phase C — Lore lexicon extraction (STRICTLY OPT-IN).

extract_lexicon() pulls short, reusable phrases (recurring names,
nicknames, running jokes) out of a Lore dump so future memes for the same
anon user can make callbacks — see intent_router.py's/segmentation.py's
lexicon_block/lexicon_instruction. It never stores or returns the dump text
itself, only the short extracted phrases, matching the non-negotiable
"never store raw dump text" rule everywhere else in this app.

schedule_lexicon_extraction() is the fire-and-forget entry point
routers/chat.py calls when a request has remember_lore=True. It runs as a
background asyncio.Task so extraction never adds latency to the SSE
response — the whole point is that it happens for FUTURE memes, not this
one. Tasks are held in a module-level set with a done-callback to discard
them; without that, asyncio.create_task()'s result can be garbage-collected
mid-flight since nothing else holds a reference to it.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from pydantic import ValidationError

import db
from config import get_settings
from nlp.llm_client import call_llm, strip_markdown
from schemas import LexiconExtractionResponse

logger = logging.getLogger(__name__)

_OVERALL_TIMEOUT_SECONDS = 45.0
_MAX_TERMS_PER_EXTRACTION = 15
_MAX_PHRASE_CHARS = 60
_MIN_TEXT_CHARS = 20  # not worth an LLM call on a trivially short message

_SYSTEM_PROMPT = f"""\
You read a group chat / conversation dump and pull out short, reusable
phrases that recur or stand out: nicknames, running jokes, recurring bits,
in-group references. Up to {_MAX_TERMS_PER_EXTRACTION} phrases, each under \
{_MAX_PHRASE_CHARS} characters, self-contained enough to be reused later
without more context (e.g. "Big Steve", "the printer incident"). If nothing
recurring or reusable stands out, return an empty list — don't force it.

Respond with ONLY valid JSON, no markdown, no explanation:
{{"terms": ["...", "..."]}}\
"""

_background_tasks: set[asyncio.Task] = set()


def _clean_terms(raw_terms: list[str]) -> list[str]:
    """Defensive post-processing regardless of what the LLM claims to have
    respected — strip, length-cap, case-insensitive dedupe, count-cap."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for term in raw_terms:
        if not isinstance(term, str):
            continue
        term = term.strip()[:_MAX_PHRASE_CHARS]
        key = term.lower()
        if not term or key in seen:
            continue
        seen.add(key)
        cleaned.append(term)
        if len(cleaned) >= _MAX_TERMS_PER_EXTRACTION:
            break
    return cleaned


async def extract_lexicon(text: str) -> list[str]:
    """Pure: text in, short phrases out. Never raises — degrades to []
    on any failure (network, malformed JSON, timeout), same "never raises
    to the caller" invariant as parse_intent/segment_contexts."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient() as client:
            raw = await asyncio.wait_for(
                call_llm(client, settings, [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ]),
                timeout=_OVERALL_TIMEOUT_SECONDS,
            )
        raw = strip_markdown(raw)
        data = json.loads(raw)
        parsed = LexiconExtractionResponse(**data)
        return _clean_terms(parsed.terms)
    except (TimeoutError, json.JSONDecodeError, ValidationError, ValueError, KeyError, httpx.HTTPError):
        return []
    except Exception:
        # Broad on purpose, matching segment_contexts()'s precedent — this
        # runs unattended in a background task with no caller to surface an
        # error to, so any unexpected failure just means no lexicon update
        # this time rather than an unhandled task exception.
        logger.exception("lexicon_extraction_failed")
        return []


async def _extract_and_store(
    anon_user_id: str, text: str, user_id: str | None, conversation_row_id: str | None
) -> None:
    terms = await extract_lexicon(text)
    if terms:
        await db.upsert_lexicon(anon_user_id, terms, user_id=user_id)
        if user_id:
            # Growth Phase H, Stage 4 — the normalized provenance write, so
            # a later per-chat delete can find and unwind exactly these
            # terms. conversation_row_id may be None (remember_lore fired
            # outside an active persisted conversation) — still tracked,
            # just never unwindable later; see insert_lexicon_terms's
            # docstring for the documented limitation.
            await db.insert_lexicon_terms(user_id, conversation_row_id, terms)


def schedule_lexicon_extraction(
    anon_user_id: str | None,
    text: str | None,
    user_id: str | None = None,
    conversation_row_id: str | None = None,
) -> None:
    """No-ops if there's no anon id (nowhere to attribute the result) or the
    text is missing/trivially short. Fire-and-forget — the caller (a
    routers/chat.py handler mid-SSE-stream) never awaits this.

    Growth Phase H, Stage 2: user_id, when present, is stamped onto the
    upserted row alongside anon_user_id (still required — see
    upsert_lexicon's docstring for why) so a signed-in user's lexicon is
    reachable by user_id from then on. Still gated on anon_user_id, not
    user_id, since the frontend always sends the anon header regardless of
    sign-in state."""
    if not anon_user_id or not text or len(text) < _MIN_TEXT_CHARS:
        return
    task = asyncio.create_task(_extract_and_store(anon_user_id, text, user_id, conversation_row_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
