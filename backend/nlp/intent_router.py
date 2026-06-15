"""
LLM intent-routing layer — powered by a local Ollama model (zero cost).

Improvements over v1:
  - Few-shot RAG: semantically similar examples retrieved from ChromaDB
    are injected into the system prompt so the model learns by example
  - JSON normalization handles the three most common LLM format deviations
    (wrapped by template_id key, field name aliases, etc.)
  - Automatic retry with a strict minimal prompt + lower temperature on
    first-attempt parse failure
  - Hard fallback: always returns a valid IntentResponse even if Ollama
    misbehaves twice
"""

from __future__ import annotations

import json
import re

import httpx
from pydantic import ValidationError

from config import get_settings
from image_processing.template_configs import DEFAULT_BOX_DESCRIPTIONS, get_config
from schemas import IntentResponse
from vector_db.chroma_client import list_template_ids
from vector_db.examples_store import get_similar_examples

_FALLBACK_TEMPLATES = [
    "drake", "distracted_boyfriend", "this_is_fine", "change_my_mind",
    "expanding_brain", "two_buttons", "success_kid", "one_does_not_simply",
    "doge", "woman_yelling_at_cat", "surprised_pikachu", "grus_plan",
    "mocking_spongebob", "hide_the_pain_harold", "buff_doge_vs_cheems",
    "batman_slapping_robin",
]


# ---------------------------------------------------------------------------
# Template catalog builder
# ---------------------------------------------------------------------------

def _build_template_catalog(template_ids: list[str]) -> dict:
    USE_WHEN: dict[str, str] = {
        "drake":                  "Rejecting one option, strongly preferring another",
        "distracted_boyfriend":   "Someone abandoning what they have for something new/tempting",
        "grus_plan":              "A plan that backfires on the last step due to an overlooked flaw",
        "woman_yelling_at_cat":   "Two-sided argument: someone angrily insisting vs calm unbothered response",
        "expanding_brain":        "Escalating takes from dumb to absurdly galaxy-brained",
        "two_buttons":            "Struggling to choose between two equally tempting or bad options",
        "this_is_fine":           "Pretending everything is okay when it's clearly not",
        "change_my_mind":         "Stating a controversial opinion and daring anyone to disagree",
        "success_kid":            "Celebrating a small, unexpected, or petty win",
        "one_does_not_simply":    "Pointing out that something is much harder than it looks",
        "doge":                   "Expressing amazement or sarcastic enthusiasm with 'wow' / 'such' phrases",
        "surprised_pikachu":      "Shocked by obvious, predictable consequences of your own actions",
        "mocking_spongebob":      "Mockingly repeating what someone said in alternating caps sarcasm",
        "hide_the_pain_harold":   "Smiling through obvious pain or pretending to be fine",
        "buff_doge_vs_cheems":    "Strong/idealized version vs weak/sad version — then vs now",
        "batman_slapping_robin":  "Interrupting and correcting someone mid-sentence",
        "always_has_been":        "Revealing a dark or ironic truth that was always the case",
        "left_exit_12":           "Swerving away from the sensible path for something tempting",
        "galaxy_brain":           "Convoluted reasoning that arrives at a wild conclusion",
        "anakin_padme":           "Assuming a positive outcome that clearly isn't happening",
    }

    catalog: dict[str, dict] = {}
    for tid in template_ids:
        config = get_config(tid)
        boxes = config.box_descriptions or DEFAULT_BOX_DESCRIPTIONS
        catalog[tid] = {
            "use_when": USE_WHEN.get(tid, "General purpose meme"),
            "text_boxes": boxes,
        }
    return catalog


# ---------------------------------------------------------------------------
# JSON normalization — handle LLM format deviations without crashing
# ---------------------------------------------------------------------------

def _normalize_llm_response(data: dict, known_ids: set[str]) -> dict:
    """
    Handles the three most common ways Ollama deviates from the expected format:

    1. Already correct: {"template_id": "...", "texts": {...}}
    2. Wrapped by template_id key: {"drake": {"texts": {...}, "reasoning": "..."}}
    3. Field name aliases: {"id": "...", "captions": {...}}
    """
    # Case 1: already correct
    if "template_id" in data and "texts" in data:
        return data

    # Case 2: the template_id was used as the outer key
    for key, value in data.items():
        if isinstance(value, dict) and "texts" in value:
            return {
                "template_id": key,
                "texts": value["texts"],
                "reasoning": value.get("reasoning", ""),
            }

    # Case 3: field name aliases
    normalized: dict = {}
    for alias in ("template_id", "id", "meme_id", "template", "meme"):
        if alias in data:
            normalized["template_id"] = data[alias]
            break
    for alias in ("texts", "captions", "text_boxes", "boxes", "labels", "caption"):
        if alias in data:
            normalized["texts"] = data[alias]
            break
    if normalized.get("template_id") and normalized.get("texts"):
        normalized["reasoning"] = data.get("reasoning", data.get("reason", ""))
        return normalized

    return data  # return as-is and let pydantic give the real error message


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are MemeGPT. Your ONLY job is to pick the perfect meme template for a user message \
and write the captions that go in each text box.

Think step by step (internally):
1. What is the user really expressing — frustration, irony, excitement, comparison?
2. Which template's structure best mirrors that emotional arc?
3. What exact text makes this funny and contextually on-point?

{few_shot_block}Available templates and their text boxes:
{template_catalog}

You MUST respond with ONLY a valid JSON object — no explanation, no markdown, nothing else:
{{
  "template_id": "<one of the template IDs above>",
  "texts": {{
    "<box_label>": "<caption for that box>",
    "<box_label>": "<caption for that box>"
  }},
  "reasoning": "<one sentence: why this template and these captions>"
}}

Rules:
- Only use template IDs and box labels exactly as listed above.
- Keep each caption under 80 characters.
- Be genuinely funny and culturally sharp — not generic.
- Omit a box entirely if it should be blank.
- Output ONLY the JSON object.\
"""

_RETRY_TEMPLATE = """\
You are a JSON API. The user said: "{user_message}"

Return ONLY this exact JSON, nothing else (no markdown, no explanation):
{{"template_id": "PICK_ONE", "texts": {{"BOX_LABEL": "CAPTION"}}, "reasoning": "WHY"}}

Available template_ids: {template_ids}

Pick the most fitting template. Fill in the text boxes with funny, on-point captions.
Output raw JSON only.\
"""


# ---------------------------------------------------------------------------
# Ollama call helper
# ---------------------------------------------------------------------------

async def _call_ollama(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_predict": 400},
    }
    try:
        response = await client.post(
            f"{settings.ollama_host}/api/chat",
            json=payload,
            timeout=90.0,
        )
        response.raise_for_status()
    except httpx.ConnectError:
        raise httpx.ConnectError(
            f"Cannot reach Ollama at {settings.ollama_host}. Run: ollama serve"
        )
    return response.json()["message"]["content"].strip()


def _strip_markdown(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    return raw.strip()


def _format_few_shot(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = ["Here are examples of how similar messages were handled:\n"]
    for ex in examples:
        texts_str = json.dumps(ex["texts"])
        lines.append(
            f'  User: "{ex["user_message"]}"\n'
            f'  → template_id: "{ex["template_id"]}", texts: {texts_str}\n'
        )
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_intent(user_message: str) -> IntentResponse:
    """
    Send `user_message` to the local Ollama model and parse the structured
    response into an IntentResponse with per-box texts.

    Retries once with a minimal prompt if the first attempt fails to parse.
    Always returns a valid IntentResponse — falls back to a hardcoded drake
    meme if both attempts fail.
    """
    settings = get_settings()
    template_ids = list_template_ids() or _FALLBACK_TEMPLATES
    known_id_set = set(template_ids)
    catalog = _build_template_catalog(template_ids)

    # Inject semantically similar examples as few-shot context
    examples = get_similar_examples(user_message, n_results=3)
    few_shot_block = _format_few_shot(examples)

    system_prompt = _SYSTEM_TEMPLATE.format(
        template_catalog=json.dumps(catalog, indent=2),
        few_shot_block=few_shot_block,
    )

    async with httpx.AsyncClient() as client:
        # Attempt 1 — rich system prompt with few-shot examples
        raw = await _call_ollama(client, settings, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ])
        raw = _strip_markdown(raw)

        try:
            data = json.loads(raw)
            data = _normalize_llm_response(data, known_id_set)
            return IntentResponse(**data)
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError):
            pass

        # Attempt 2 — minimal strict prompt, lower temperature for more reliable JSON
        retry_prompt = _RETRY_TEMPLATE.format(
            user_message=user_message,
            template_ids=", ".join(template_ids[:14]),
        )
        raw = await _call_ollama(client, settings, [
            {"role": "user", "content": retry_prompt},
        ], temperature=0.2)
        raw = _strip_markdown(raw)

        try:
            data = json.loads(raw)
            data = _normalize_llm_response(data, known_id_set)
            return IntentResponse(**data)
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError):
            pass

    # Hard fallback — always returns something rather than 500ing
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={
            "top_text": user_message[:60] if len(user_message) <= 60 else user_message[:57] + "...",
            "bottom_text": "This is fine.",
        },
        reasoning="Fallback: model failed to produce valid JSON on both attempts",
    )
