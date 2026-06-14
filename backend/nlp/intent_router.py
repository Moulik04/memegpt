"""
LLM intent-routing layer.

Converts a free-form user chat message into a structured IntentResponse
(template_id + top_text + bottom_text) using Claude's JSON mode via the
Anthropic SDK.  The response is parsed strictly against the IntentResponse
schema; a ValueError is raised if the model returns malformed JSON.
"""

from __future__ import annotations

import json
import re

import anthropic

from schemas import IntentResponse

_client = anthropic.Anthropic()

# Known seed templates — extend as you add images to backend/templates/
KNOWN_TEMPLATES = [
    "drake",
    "distracted_boyfriend",
    "this_is_fine",
    "change_my_mind",
    "expanding_brain",
    "two_buttons",
    "success_kid",
    "one_does_not_simply",
    "doge",
    "galaxy_brain",
]

_SYSTEM_PROMPT = f"""You are MemeGPT's intent parser. Given a user's chat message, determine the most contextually appropriate meme template and generate funny, on-point captions.

Available template IDs:
{json.dumps(KNOWN_TEMPLATES, indent=2)}

Respond ONLY with a valid JSON object matching this schema — no markdown fences, no extra keys:
{{
  "template_id": "<one of the IDs above>",
  "top_text": "<caption for the top of the meme>",
  "bottom_text": "<caption for the bottom of the meme>",
  "reasoning": "<one sentence explaining why this template fits>"
}}

Rules:
- Be genuinely funny and culturally aware.
- Keep each caption under 80 characters.
- top_text or bottom_text may be empty strings if the template only needs one caption.
- Always return valid JSON."""


async def parse_intent(user_message: str) -> IntentResponse:
    """
    Send `user_message` to Claude and parse the returned JSON into an IntentResponse.

    Raises:
        ValueError: if the model returns JSON that doesn't match the schema.
        anthropic.APIError: on API-level failures (propagated to caller).
    """
    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    # Strip accidental markdown code fences the model might add
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON: {raw!r}") from exc

    # Validate against schema — pydantic raises ValidationError on bad fields
    return IntentResponse(**data)
