"""
LLM intent-routing layer — powered by a local Ollama model (zero cost).

Features:
  - Few-shot RAG: semantically similar examples retrieved from ChromaDB injected into prompt
  - avoid_templates: conversation memory prevents template repetition within a session
  - JSON normalization: handles 3 common LLM output format deviations
  - Retry with strict prompt + lower temperature on parse failure
  - Hard fallback: always returns a valid IntentResponse — never raises to the caller
"""

from __future__ import annotations

import json
import re

import httpx
from pydantic import ValidationError

from config import get_settings
from image_processing.template_configs import DEFAULT_BOX_DESCRIPTIONS, get_config
from schemas import IntentResponse
from vector_db.chroma_client import list_template_ids, query_similar_memes
from vector_db.examples_store import get_similar_examples

_FALLBACK_TEMPLATES = [
    "drake", "distracted_boyfriend", "this_is_fine", "change_my_mind",
    "expanding_brain", "two_buttons", "success_kid", "one_does_not_simply",
    "doge", "woman_yelling_at_cat", "surprised_pikachu", "grus_plan",
    "mocking_spongebob", "hide_the_pain_harold", "buff_doge_vs_cheems",
    "batman_slapping_robin",
]

# Always included in every prompt regardless of RAG results
_CORE_TEMPLATE_IDS = [
    "drake", "distracted_boyfriend", "grus_plan", "woman_yelling_at_cat",
    "expanding_brain", "two_buttons", "surprised_pikachu",
    "hide_the_pain_harold", "this_is_fine", "mocking_spongebob",
    "change_my_mind", "batman_slapping_robin",
    "buff_doge_vs_cheems", "boardroom_meeting_suggestion",
]

USE_WHEN: dict[str, str] = {
    # --- Core templates (explicitly configured layouts) ---
    "drake":                   "Rejecting one option and strongly preferring another — comparison or upgrade",
    "distracted_boyfriend":    "Someone ignoring what they have to chase something new/tempting",
    "grus_plan":               "A plan that has an obvious flaw revealed on the last step",
    "woman_yelling_at_cat":    "Two-sided argument: someone raging vs calm unbothered response",
    "expanding_brain":         "Escalating takes from basic/dumb to absurdly galaxy-brained",
    "two_buttons":             "Agonizing between two equally tempting or equally bad choices",
    "always_has_been":         "Revealing a dark or ironic truth that was always the case",
    "batman_slapping_robin":   "Interrupting someone mid-sentence to correct them sharply",
    "buff_doge_vs_cheems":     "Comparing two states of the same person/thing — past vs present, rested vs exhausted, 2am energy vs 9am regret, before vs after, idealized vs reality",
    "surprised_pikachu":       "Shocked by the obvious, predictable consequences of your own actions",
    "left_exit_12":            "Abandoning the sensible planned path to swerve toward something tempting",
    "change_my_mind":          "Stating a bold controversial opinion at a table and daring anyone to argue",
    "anakin_padme":            "Assuming a positive outcome that clearly isn't happening — silent confirmation",
    "doge":                    "Wow, much, very, many — comically enthusiastic amazement or ironic enthusiasm",
    "galaxy_brain":            "Increasingly absurd logic chain that arrives at a wild conclusion",
    # --- Standard top/bottom single-panel templates ---
    "this_is_fine":            "Denial mode — sitting in literal chaos or disaster and refusing to acknowledge it; only fill 'situation' box describing the chaos — 'this is fine' is already printed in the image; NOT for happy discoveries or good news",
    "boardroom_meeting_suggestion": "An idea gets suggested and everyone piles on with the same bad take — boss throws them all out; use for repeated bad suggestions, groupthink, or ideas that always get shot down",
    "success_kid":             "Celebrating a small, unexpected, or petty win with a fist pump",
    "one_does_not_simply":     "Pointing out that something people think is easy is actually very hard",
    "mocking_spongebob":       "Mockingly repeating what someone said in alternating caps to show it's dumb",
    "hide_the_pain_harold":    "Smiling through obvious pain while projecting a fine public face — inner suffering vs outer performance; great for pretending to understand something you don't",
    "futurama_fry":            "Squinting with suspicion — not sure if X is real or just another stupid thing",
    "the_most_interesting_man": "A refined statement about something you simply never do — for grandiose declarations",
    "y_u_no":                  "Demanding to know why someone doesn't just do the obvious thing already",
    "ancient_aliens":          "Blaming aliens or a conspiracy for something with a perfectly ordinary explanation",
    "first_world_problems":    "Dramatically suffering over a trivial first-world inconvenience while crying",
    "bad_luck_brian":          "A person whose every attempt backfires spectacularly — worst case scenario every time",
    "good_guy_greg":           "Someone being unexpectedly considerate and wholesome when they don't have to be",
    "scumbag_steve":           "Someone acting obnoxious, selfish, or socially unaware in a painfully familiar way",
    "grumpy_cat":              "Categorical absolute refusal or negativity — 'No.' to literally everything",
    "philosoraptor":           "A deep philosophical question that sounds absurd but is surprisingly hard to answer",
    "bernie_sanders":          "Bernie sitting stoically with mittens — for cozy, unbothered, or deadpan observations",
    "stonks":                  "Making a terrible decision that somehow looks profitable on paper — absurd business logic",
    "crying_cat":              "Genuine despair or sadness, possibly over something trivial",
    "rollsafe":                "Using clever but flawed logic to avoid a problem — 'can't X if you never Y'",
    "disaster_girl":           "Watching chaos unfold with a satisfied smirk — enjoying someone else's downfall",
    "monkey_puppet":           "Awkwardly side-eyeing and looking away when something uncomfortable is said",
    "arthur_fist":             "Clenching fist in barely-contained rage — about to completely lose it",
    "kermit_tea":              "Passive-aggressively observing something about others while claiming it's none of your business",
    "oprah":                   "Giving the same thing to absolutely everyone — wild generosity or unfair equal distribution",
    "jack_sparrow":            "Being genuinely perplexed by something that technically makes sense but really shouldn't",
    "giga_chad":               "Making an extremely confident take and refusing to elaborate, justify, or apologize",
    "crying_laughing":         "Something is so absurd that you're genuinely unsure whether to laugh or cry",
    "notice_me_senpai":        "Desperately wanting attention from someone who completely doesn't notice you",
    "my_brain_is_full":        "So overwhelmed with information that you can't absorb any more",
    "all_the_things":          "Enthusiastically deciding to do literally all the things at once",
    "confession_bear":         "Admitting something embarrassing, shameful, or guilty in a deadpan format",
    "third_world_skeptical":   "Raising an eyebrow at a claim that sounds too convenient or good to be true",
    "socially_awkward_penguin": "Being completely paralyzed by social anxiety in a perfectly normal situation",
    "bad_pun_dog":             "A dog grinning smugly after making an absolutely terrible pun — for wordplay",
    "sean_bean_lotr":          "Brace yourself — something is coming; or pointing out something inevitable",
    "10_guy":                  "An oblivious person making a surprisingly deep or dumb observation while clearly out of it",
    "college_liberal":         "An idealistic take on a social issue that sounds good on paper but misses reality",
    "overly_attached_girlfriend": "When someone is way too clingy, possessive, or intense in a relationship",
    "first_day_on_internet":   "Someone discovering an obviously old internet meme and sharing it like it's new",
    "grandma_finds_internet":  "An older person encountering technology or internet culture and being baffled",
    "harold_hide_pain":        "Smiling through obvious pain — same vibe as hide_the_pain_harold",
    "meme_man":                "Stonks-adjacent — making an extremely logical or completely unhinged observation",
    "chad":                    "Ultra-confident stance on something that would normally be controversial or nerdy",
    "virgin_vs_chad":          "Contrasting the insecure weak approach with the ultra-confident chad approach",
    "trade_offer":             "I receive X. You receive Y — for lopsided or ironic deal proposals",
    "they_are_the_same_picture": "Pointing out that two things people treat as different are actually identical",
    "wait_that_s_illegal":     "Realizing something you've been doing is technically not allowed",
    "i_was_told":              "Expecting one thing and getting something completely different",
    "uno_reverse":             "Turning someone's argument or action right back on them",
    "megamind":                "No one said you couldn't do the thing — technically correct loophole logic",
    "is_this_a_pigeon":        "Confidently misidentifying something obvious — labeling the wrong thing incorrectly",
    "ight_imma_head_out":      "Spongebob getting up to leave — when something awkward or bad happens and you just go",
}


def _build_template_catalog(template_ids: list[str]) -> dict:
    """
    Compact format — w = when to use, b = list of box label names.
    Omitting full box descriptions saves ~50% tokens vs the verbose format.
    """
    catalog: dict[str, dict] = {}
    for tid in template_ids:
        config = get_config(tid)
        boxes = config.box_descriptions or DEFAULT_BOX_DESCRIPTIONS
        catalog[tid] = {
            "w": USE_WHEN.get(tid, "general meme with top and bottom text"),
            "b": list(boxes.keys()),
        }
    return catalog


def _normalize_llm_response(data: dict, known_ids: set[str]) -> dict:
    """
    Handle common LLM JSON format deviations:
    1. Already correct: {"template_id": "...", "texts": {...}}
    2. Wrapped by template_id: {"drake": {"texts": {...}, "reasoning": "..."}}
    3. Field name aliases: {"id": "...", "captions": {...}}
    """
    if "template_id" in data and "texts" in data:
        return data

    for key, value in data.items():
        if isinstance(value, dict) and "texts" in value:
            return {
                "template_id": key,
                "texts": value["texts"],
                "reasoning": value.get("reasoning", ""),
            }

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

    return data


def _format_few_shot(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = ["Here are examples of how similar messages were handled:\n"]
    for ex in examples:
        lines.append(
            f'  User: "{ex["user_message"]}"\n'
            f'  → template_id: "{ex["template_id"]}", texts: {json.dumps(ex["texts"])}\n'
        )
    return "\n".join(lines) + "\n\n"


_SYSTEM_TEMPLATE = """\
You are MemeGPT. Pick the best meme template and write captions for the user's message.

Catalog format: each key is a template_id. "w" = when to use it. "b" = box label names \
(use these exact labels in your "texts" output).

{few_shot_block}{avoid_block}Templates:
{template_catalog}

Respond with ONLY valid JSON — no markdown, no explanation:
{{
  "template_id": "<id from catalog>",
  "texts": {{"<box_label>": "<caption>"}},
  "reasoning": "<one sentence why>"
}}

Rules: use only template_ids and box labels listed above; captions under 80 chars; be funny.\
"""

_RETRY_TEMPLATE = """\
You are a JSON API. The user said: "{user_message}"

Return ONLY this exact JSON, nothing else:
{{"template_id": "PICK_ONE", "texts": {{"BOX_LABEL": "CAPTION"}}, "reasoning": "WHY"}}

Available template_ids: {template_ids}

Output raw JSON only — no markdown, no explanation.\
"""


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
        "options": {"temperature": temperature, "num_predict": 150},
    }
    try:
        base = settings.ollama_host.rstrip("/")
        response = await client.post(
            f"{base}/api/chat",
            json=payload,
            headers={"ngrok-skip-browser-warning": "true"},
            follow_redirects=True,
            timeout=120.0,
        )
        response.raise_for_status()
    except httpx.ConnectError:
        raise httpx.ConnectError(
            f"Cannot reach Ollama at {settings.ollama_host}. Run: ollama serve"
        )
    return response.json()["message"]["content"].strip()


async def _call_groq(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    """Groq cloud inference — free tier, ~400 t/s, no GPU required."""
    response = await client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json={
            "model": settings.groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        },
        headers={
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


async def _call_llm(
    client: httpx.AsyncClient,
    settings,
    messages: list[dict],
    temperature: float = 0.75,
) -> str:
    """Route to Groq (cloud) or Ollama (local) based on LLM_PROVIDER config."""
    if settings.llm_provider == "groq" and settings.groq_api_key:
        return await _call_groq(client, settings, messages, temperature)
    return await _call_ollama(client, settings, messages, temperature)


def _strip_markdown(raw: str) -> str:
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    return raw.strip()


async def parse_intent(
    user_message: str,
    avoid_templates: list[str] | None = None,
) -> IntentResponse:
    """
    Route a user message to the best meme template + captions.

    avoid_templates: list of recently used template IDs in this conversation —
    injected into the prompt to prevent repetition.
    """
    settings = get_settings()

    # All known IDs (used for validation only — NOT sent wholesale to the LLM)
    all_ids = list_template_ids() or _FALLBACK_TEMPLATES
    known_id_set = set(all_ids)

    # RAG pre-filter: find the 8 most semantically relevant templates for this message
    rag_results = query_similar_memes(user_message, n_results=8)
    rag_ids = [r["id"] for r in rag_results if r.get("id") in known_id_set]

    # Final catalog: RAG results first, then core templates, deduplicated, max 20
    # This keeps the prompt well under 4096 tokens regardless of collection size
    prompt_ids = list(dict.fromkeys(rag_ids + _CORE_TEMPLATE_IDS))[:20]
    template_ids = prompt_ids  # used in retry prompt below
    catalog = _build_template_catalog(prompt_ids)

    examples = get_similar_examples(user_message, n_results=3)
    few_shot_block = _format_few_shot(examples)

    avoid_block = ""
    if avoid_templates:
        avoid_block = (
            f"IMPORTANT — DO NOT repeat these recently used templates: "
            f"{', '.join(avoid_templates)}. Pick something different and fresh.\n\n"
        )

    system_prompt = _SYSTEM_TEMPLATE.format(
        template_catalog=json.dumps(catalog, indent=2),
        few_shot_block=few_shot_block,
        avoid_block=avoid_block,
    )

    async with httpx.AsyncClient() as client:
        # Attempt 1 — rich prompt with few-shot + avoid block
        raw = await _call_llm(client, settings, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ])
        raw = _strip_markdown(raw)
        try:
            data = json.loads(raw)
            data = _normalize_llm_response(data, known_id_set)
            result = IntentResponse(**data)
            if result.template_id not in known_id_set:
                raise ValueError(f"Hallucinated template_id: {result.template_id}")
            return result
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError):
            pass

        # Attempt 2 — minimal strict prompt at low temperature
        retry_prompt = _RETRY_TEMPLATE.format(
            user_message=user_message,
            template_ids=", ".join(template_ids[:14]),
        )
        raw = await _call_llm(client, settings, [
            {"role": "user", "content": retry_prompt},
        ], temperature=0.2)
        raw = _strip_markdown(raw)
        try:
            data = json.loads(raw)
            data = _normalize_llm_response(data, known_id_set)
            result = IntentResponse(**data)
            if result.template_id not in known_id_set:
                raise ValueError(f"Hallucinated template_id: {result.template_id}")
            return result
        except (json.JSONDecodeError, ValidationError, ValueError, KeyError):
            pass

    # Hard fallback — always returns something rather than 500-ing
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={
            "top_text": user_message[:60] if len(user_message) <= 60 else user_message[:57] + "...",
            "bottom_text": "This is fine.",
        },
        reasoning="Fallback: model failed to produce valid JSON on both attempts",
    )
