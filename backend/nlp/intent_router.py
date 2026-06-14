"""
LLM intent-routing layer — powered by a local Ollama model (zero cost).

Converts a free-form user message into a structured IntentResponse
(template_id + top_text + bottom_text) by calling the Ollama /api/chat
endpoint with JSON mode enabled.

Template IDs are fetched live from ChromaDB so the prompt always reflects
whatever templates are actually seeded — no manual sync needed.

Setup (one-time):
    brew install ollama
    ollama pull llama3.1:8b
    ollama serve          # or it auto-starts on macOS
"""

from __future__ import annotations

import json
import re

import httpx

from config import get_settings
from schemas import IntentResponse
from vector_db.chroma_client import list_template_ids

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

_SYSTEM_TEMPLATE = """\
You are MemeGPT's intent parser. Given a user's chat message, pick the best meme \
template and write funny captions for it.

Available template IDs (you MUST use one of these exactly):
{template_ids}

You MUST respond with ONLY a JSON object — no explanation, no markdown, no extra text:
{{
  "template_id": "<one of the IDs above>",
  "top_text": "<caption for the top of the meme, max 80 chars>",
  "bottom_text": "<caption for the bottom of the meme, max 80 chars>",
  "reasoning": "<one sentence: why this template fits>"
}}

Rules:
- Be genuinely funny and culturally aware.
- top_text or bottom_text may be an empty string if the template works with one caption.
- Never invent a template_id that isn't in the list above.
- Output raw JSON only — no code fences, no prose.\
"""


async def parse_intent(user_message: str) -> IntentResponse:
    """
    Call the local Ollama model and parse its response into an IntentResponse.

    Raises:
        httpx.ConnectError: if Ollama isn't running (start with: ollama serve)
        ValueError: if the model returns malformed JSON
    """
    settings = get_settings()

    template_ids = list_template_ids() or _FALLBACK_TEMPLATES
    system_prompt = _SYSTEM_TEMPLATE.format(
        template_ids=json.dumps(template_ids, indent=2)
    )

    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "format": "json",   # Ollama JSON mode — guarantees valid JSON output
        "options": {
            "temperature": 0.7,
            "num_predict": 256,
        },
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.ollama_host}/api/chat",
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
        except httpx.ConnectError:
            raise httpx.ConnectError(
                f"Cannot reach Ollama at {settings.ollama_host}. "
                "Make sure it's running: ollama serve"
            )

    raw = response.json()["message"]["content"].strip()

    # Strip accidental markdown fences (some models ignore the instruction)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned non-JSON: {raw!r}") from exc

    # Validate against schema — Pydantic raises ValidationError on bad fields
    return IntentResponse(**data)
