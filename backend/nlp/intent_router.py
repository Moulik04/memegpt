"""
LLM intent-routing layer.

Converts a free-form user chat message into a structured IntentResponse
(template_id + top_text + bottom_text) using Claude via the async Anthropic SDK.

Template IDs are fetched live from ChromaDB so the prompt always reflects
whatever templates are actually available on disk — no manual sync needed.
"""

from __future__ import annotations

import json
import re

import anthropic

from schemas import IntentResponse
from vector_db.chroma_client import list_template_ids

_client = anthropic.AsyncAnthropic()

# Fallback list used only when ChromaDB is empty (e.g. before first seed run)
_FALLBACK_TEMPLATES = [
    "drake",
    "distracted_boyfriend",
    "this_is_fine",
    "change_my_mind",
    "expanding_brain",
    "two_buttons",
    "success_kid",
    "one_does_not_simply",
    "doge",
    "woman_yelling_at_cat",
    "surprised_pikachu",
    "grus_plan",
    "mocking_spongebob",
    "hide_the_pain_harold",
    "buff_doge_vs_cheems",
    "batman_slapping_robin",
]

_SYSTEM_TEMPLATE = """You are MemeGPT's intent parser. Given a user's chat message, determine the most contextually appropriate meme template and generate funny, on-point captions.

Available template IDs:
{template_ids}

Respond ONLY with a valid JSON object — no markdown fences, no extra keys:
{{
  "template_id": "<one of the IDs above>",
  "top_text": "<caption for the top of the meme>",
  "bottom_text": "<caption for the bottom of the meme>",
  "reasoning": "<one sentence explaining why this template fits>"
}}

Rules:
- Be genuinely funny and culturally aware.
- Keep each caption under 80 characters.
- top_text or bottom_text may be an empty string if the template works better with a single caption.
- Always pick from the available template IDs — never invent a new one.
- Always return valid JSON."""


async def parse_intent(user_message: str) -> IntentResponse:
    """
    Send `user_message` to Claude and parse the returned JSON into an IntentResponse.

    Raises:
        ValueError: if the model returns JSON that doesn't match the schema.
        anthropic.APIError: on API-level failures (propagated to caller).
    """
    # Pull live template list from ChromaDB; fall back to defaults if empty
    template_ids = list_template_ids() or _FALLBACK_TEMPLATES
    system_prompt = _SYSTEM_TEMPLATE.format(
        template_ids=json.dumps(template_ids, indent=2)
    )

    response = await _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    # Strip accidental markdown code fences the model might add
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON: {raw!r}") from exc

    # Validate against schema — Pydantic raises ValidationError on bad fields
    return IntentResponse(**data)
