"""
The second model's reply is held to a JSON schema built from the candidates
in its prompt (Groq structured outputs, strict mode), so it cannot come back
as malformed JSON. The primary model's requests are left as they were.

Groq may still refuse a schema request with a 400. That request is sent once
more as a plain JSON one, which is what every request was before.

Uses httpx.MockTransport, same as test_llm_client.py. No network call.
"""

from __future__ import annotations

import json

import httpx
import pytest

from config import Settings
from image_processing.template_configs import get_config
from nlp import intent_router
from nlp.intent_router import _CORE_TEMPLATE_IDS, _FALLBACK_TEMPLATES, parse_intent
from nlp.llm_client import call_groq

_PRIMARY = "qwen/qwen3.6-27b"
_SECOND = "openai/gpt-oss-120b"
_MESSAGES = [{"role": "user", "content": "the retry prompt"}]
_DRAKE = '{"template_id": "drake", "texts": {"rejected_option": "a", "approved_option": "b"}, "reasoning": "c"}'
_SCHEMA = {
    "type": "object",
    "properties": {"template_id": {"type": "string"}},
    "required": ["template_id"],
    "additionalProperties": False,
}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="groq",
        groq_api_key="fake-key",
        groq_model=_PRIMARY,
        groq_fallback_model=_SECOND,
    )


def _second_model_settings() -> Settings:
    return _settings().model_copy(update={"groq_model": _SECOND})


def _answer(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _refused() -> httpx.Response:
    body = {"error": {"message": "Failed to generate JSON.", "code": "json_validate_failed"}}
    return httpx.Response(400, json=body)


def _client(responses: list[httpx.Response], seen: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return responses[min(len(seen), len(responses)) - 1]

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _objects(schema: dict) -> list[dict]:
    """Every object schema inside `schema`, itself included."""
    found = [schema] if schema.get("type") == "object" else []
    for value in schema.get("properties", {}).values():
        found += _objects(value)
    for branch in schema.get("anyOf", []):
        found += _objects(branch)
    return found


def _label_sets(schema: dict) -> list[set[str]]:
    return [set(branch["properties"]) for branch in schema["properties"]["texts"]["anyOf"]]


# --- the request ------------------------------------------------------------


async def test_a_schema_goes_out_as_a_strict_structured_output_request():
    seen: list[dict] = []
    async with _client([_answer(_DRAKE)], seen) as client:
        result = await call_groq(client, _second_model_settings(), _MESSAGES, json_schema=_SCHEMA)

    assert result == _DRAKE
    assert seen[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "meme_pick", "strict": True, "schema": _SCHEMA},
    }


async def test_a_refused_schema_request_is_sent_once_more_as_a_plain_json_one():
    seen: list[dict] = []
    async with _client([_refused(), _answer(_DRAKE)], seen) as client:
        result = await call_groq(client, _second_model_settings(), _MESSAGES, json_schema=_SCHEMA)

    assert result == _DRAKE
    assert [s["response_format"]["type"] for s in seen] == ["json_schema", "json_object"]
    assert seen[0]["messages"] == seen[1]["messages"]


async def test_a_request_refused_both_ways_is_not_sent_a_third_time():
    seen: list[dict] = []
    async with _client([_refused()], seen) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await call_groq(client, _second_model_settings(), _MESSAGES, json_schema=_SCHEMA)

    assert [s["response_format"]["type"] for s in seen] == ["json_schema", "json_object"]


# --- the schema -------------------------------------------------------------


def test_the_schema_offers_the_prompts_candidates_and_no_others():
    schema = intent_router._pick_schema(["drake", "two_buttons", "this_is_fine"])

    assert schema["properties"]["template_id"]["enum"] == ["drake", "two_buttons", "this_is_fine"]


def test_a_reply_using_any_candidates_real_box_labels_fits_the_schema():
    candidates = list(dict.fromkeys(_CORE_TEMPLATE_IDS + _FALLBACK_TEMPLATES))
    label_sets = _label_sets(intent_router._pick_schema(candidates))

    for template_id in candidates:
        labels = {box.label for box in get_config(template_id).text_boxes}
        assert labels in label_sets, template_id


def test_templates_with_the_same_boxes_share_one_entry():
    same_boxes = [t for t in _FALLBACK_TEMPLATES if {b.label for b in get_config(t).text_boxes} == {"top_text", "bottom_text"}]
    assert len(same_boxes) >= 2

    assert _label_sets(intent_router._pick_schema(same_boxes)) == [{"top_text", "bottom_text"}]


def test_the_schema_keeps_to_strict_modes_rules():
    """Strict mode takes an object only if every property is required and
    nothing else is allowed in."""
    schema = intent_router._pick_schema(list(dict.fromkeys(_CORE_TEMPLATE_IDS + _FALLBACK_TEMPLATES)))

    assert list(schema["properties"]) == ["template_id", "texts", "reasoning"]
    objects = _objects(schema)
    assert len(objects) > 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])


# --- the router -------------------------------------------------------------


async def test_only_the_second_model_is_given_a_schema(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    asked: list[tuple[str, dict | None]] = []

    async def only_the_second_model_answers(client, settings, messages, temperature=0.75, **kwargs):
        asked.append((settings.groq_model, kwargs.get("json_schema")))
        return _DRAKE if settings.groq_model == _SECOND else "not valid json"

    monkeypatch.setattr(intent_router, "call_llm", only_the_second_model_answers)

    result = await parse_intent("anything")

    assert result.template_id == "drake"
    assert [model for model, _ in asked] == [_PRIMARY, _PRIMARY, _SECOND]
    assert [schema for _, schema in asked[:2]] == [None, None]
    assert "drake" in asked[2][1]["properties"]["template_id"]["enum"]


async def test_the_schema_names_the_same_candidates_as_the_prompt_it_goes_with(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", _settings)

    async def fixed_candidates(user_message, known_id_set):
        return ["drake", "two_buttons"]

    schemas: list[dict] = []

    async def only_the_second_model_answers(client, settings, messages, temperature=0.75, **kwargs):
        if settings.groq_model != _SECOND:
            return "not valid json"
        schemas.append(kwargs["json_schema"])
        return _DRAKE

    monkeypatch.setattr(intent_router, "resolve_prompt_template_ids", fixed_candidates)
    monkeypatch.setattr(intent_router, "call_llm", only_the_second_model_answers)

    await parse_intent("anything")

    assert schemas[0]["properties"]["template_id"]["enum"] == ["drake", "two_buttons"]


async def test_a_refused_schema_request_still_ends_in_a_second_model_pick_end_to_end(monkeypatch):
    """Router and Groq call together, with only the network faked: the
    primary model's replies are unusable, the second model's schema request
    is refused, and its plain request is answered."""
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    seen: list[dict] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        seen.append(sent)
        if sent["model"] == _PRIMARY:
            return _answer("not valid json")
        return _refused() if sent["response_format"]["type"] == "json_schema" else _answer(_DRAKE)

    monkeypatch.setattr(
        intent_router.httpx, "AsyncClient", lambda: real_client(transport=httpx.MockTransport(handler))
    )

    result = await parse_intent("anything")

    assert (result.template_id, result.model_used) == ("drake", "second")
    assert [(s["model"], s["response_format"]["type"]) for s in seen] == [
        (_PRIMARY, "json_object"),
        (_PRIMARY, "json_object"),
        (_SECOND, "json_schema"),
        (_SECOND, "json_object"),
    ]
