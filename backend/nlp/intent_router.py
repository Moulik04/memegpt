"""
LLM intent-routing layer — powered by a local Ollama model (zero cost).

The system prompt is built dynamically from template_configs.py so the model
knows exactly what text boxes each template has and what goes in each one.
This is the same insight as the Imgflip character-level model: encode
template ID + box index into the generation context.
"""

from __future__ import annotations

import json
import re

import httpx

from config import get_settings
from image_processing.template_configs import DEFAULT_BOX_DESCRIPTIONS, get_config
from schemas import IntentResponse
from vector_db.chroma_client import list_template_ids

_FALLBACK_TEMPLATES = [
    "drake", "distracted_boyfriend", "this_is_fine", "change_my_mind",
    "expanding_brain", "two_buttons", "success_kid", "one_does_not_simply",
    "doge", "woman_yelling_at_cat", "surprised_pikachu", "grus_plan",
    "mocking_spongebob", "hide_the_pain_harold", "buff_doge_vs_cheems",
    "batman_slapping_robin",
]


def _build_template_catalog(template_ids: list[str]) -> dict:
    """
    Build a rich per-template dict injected into the system prompt.
    Includes usage description and per-box meaning for each template.
    """
    # Inline descriptions — what each template is for and when to use it
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


_SYSTEM_TEMPLATE = """\
You are MemeGPT. Your ONLY job is to pick the perfect meme template for a user message \
and write the captions that go in each text box.

Think step by step (internally):
1. What is the user really expressing — frustration, irony, excitement, comparison?
2. Which template's structure best mirrors that emotional arc?
3. What exact text makes this funny and contextually on-point?

Available templates and their text boxes:
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
- Omit a box entirely (don't include its key) if it should be blank.
- Output ONLY the JSON object.\
"""


async def parse_intent(user_message: str) -> IntentResponse:
    """
    Send `user_message` to the local Ollama model and parse the structured
    response into an IntentResponse with per-box texts.
    """
    settings = get_settings()

    template_ids = list_template_ids() or _FALLBACK_TEMPLATES
    catalog = _build_template_catalog(template_ids)
    system_prompt = _SYSTEM_TEMPLATE.format(
        template_catalog=json.dumps(catalog, indent=2)
    )

    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.75, "num_predict": 400},
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.ollama_host}/api/chat",
                json=payload,
                timeout=90.0,
            )
            response.raise_for_status()
        except httpx.ConnectError:
            raise httpx.ConnectError(
                f"Cannot reach Ollama at {settings.ollama_host}. "
                "Run: ollama serve"
            )

    raw = response.json()["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model returned non-JSON: {raw!r}") from exc

    return IntentResponse(**data)
