"""
The second model's reply is held to a JSON schema built from the candidates
in its prompt (Groq structured outputs, strict mode), so it cannot come back
as malformed JSON. The primary model's requests are left as they were.

Under the schema the captions are a list of {"box", "caption"} entries, not
an object keyed by box label. Strict mode cannot describe an object that
holds only some of a known set of keys, and Groq refuses an anyOf whose
entries share a key. The second model's prompt asks for the same list.

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
from nlp.intent_router import _CORE_TEMPLATE_IDS, _FALLBACK_TEMPLATES, _build_retry_prompt, is_fallback, parse_intent
from nlp.llm_client import call_groq

_PRIMARY = "qwen/qwen3.6-27b"
_SECOND = "openai/gpt-oss-120b"
_MESSAGES = [{"role": "user", "content": "the retry prompt"}]
_DRAKE = (
    '{"template_id": "drake", "texts": [{"box": "rejected_option", "caption": "a"}, '
    '{"box": "approved_option", "caption": "b"}], "reasoning": "c"}'
)
_SCHEMA = {
    "type": "object",
    "properties": {"template_id": {"type": "string"}},
    "required": ["template_id"],
    "additionalProperties": False,
}
_CANDIDATES = list(dict.fromkeys(_CORE_TEMPLATE_IDS + _FALLBACK_TEMPLATES))


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
    body = {"error": {"message": "invalid JSON schema for response_format", "type": "invalid_request_error"}}
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
    if "items" in schema:
        found += _objects(schema["items"])
    return found


def _second_model_replies(monkeypatch, reply: str) -> list[dict]:
    """The primary model's replies are unusable and the second model answers
    `reply`. Returns what each call was given, in order."""
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    asked: list[dict] = []

    async def only_the_second_model_answers(client, settings, messages, temperature=0.75, **kwargs):
        asked.append({"model": settings.groq_model, "prompt": messages[-1]["content"], **kwargs})
        return reply if settings.groq_model == _SECOND else "not valid json"

    monkeypatch.setattr(intent_router, "call_llm", only_the_second_model_answers)
    return asked


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


def test_a_caption_can_only_go_in_a_box_one_of_the_candidates_has():
    schema = intent_router._pick_schema(_CANDIDATES)

    boxes = schema["properties"]["texts"]["items"]["properties"]["box"]["enum"]
    real = {box.label for template_id in _CANDIDATES for box in get_config(template_id).text_boxes}
    assert set(boxes) == real
    assert len(boxes) == len(real)


def test_the_schema_keeps_to_strict_modes_rules():
    """Strict mode takes an object only if every property is required and
    nothing else is allowed in."""
    schema = intent_router._pick_schema(_CANDIDATES)

    assert list(schema["properties"]) == ["template_id", "texts", "reasoning"]
    objects = _objects(schema)
    assert len(objects) == 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])


def test_the_schema_has_no_alternatives_for_groq_to_refuse():
    """Groq turns down an anyOf whose entries share a key, and box labels
    are shared between templates."""
    assert "anyOf" not in json.dumps(intent_router._pick_schema(_CANDIDATES))


# --- the prompt -------------------------------------------------------------


def test_the_second_models_prompt_asks_for_the_shape_its_schema_allows():
    prompt = _build_retry_prompt("anything", ["drake", "two_buttons"], captions_as_list=True)

    assert '"texts": [{"box": "<real box label>", "caption": "<caption>"}]' in prompt
    for template_id in ("drake", "two_buttons"):
        assert json.dumps(intent_router.USE_WHEN[template_id]) in prompt
        for box in get_config(template_id).text_boxes:
            assert box.label in prompt


def test_the_retry_prompt_itself_still_asks_for_captions_keyed_by_box():
    prompt = _build_retry_prompt("anything", ["drake", "two_buttons"])

    assert '"texts": {"<real box label>": "<caption>"}' in prompt
    assert '"box"' not in prompt


# --- the router -------------------------------------------------------------


async def test_only_the_second_model_is_given_a_schema_and_the_prompt_that_goes_with_it(monkeypatch):
    asked = _second_model_replies(monkeypatch, _DRAKE)

    result = await parse_intent("anything")

    assert result.template_id == "drake"
    assert [a["model"] for a in asked] == [_PRIMARY, _PRIMARY, _SECOND]
    assert [a.get("json_schema") for a in asked[:2]] == [None, None]
    assert '"box"' not in asked[1]["prompt"]
    assert "drake" in asked[2]["json_schema"]["properties"]["template_id"]["enum"]
    assert '"box"' in asked[2]["prompt"]


async def test_the_schema_names_the_same_candidates_as_the_prompt_it_goes_with(monkeypatch):
    asked = _second_model_replies(monkeypatch, _DRAKE)

    async def fixed_candidates(user_message, known_id_set):
        return ["drake", "two_buttons"]

    monkeypatch.setattr(intent_router, "resolve_prompt_template_ids", fixed_candidates)

    await parse_intent("anything")

    assert asked[2]["json_schema"]["properties"]["template_id"]["enum"] == ["drake", "two_buttons"]
    assert asked[2]["prompt"] == _build_retry_prompt("anything", ["drake", "two_buttons"], captions_as_list=True)


async def test_captions_written_as_a_list_end_up_keyed_by_box(monkeypatch):
    _second_model_replies(monkeypatch, _DRAKE)

    result = await parse_intent("anything")

    assert result.texts == {"rejected_option": "a", "approved_option": "b"}
    assert (result.prompt_used, result.model_used) == ("retry", "second")


async def test_a_caption_for_a_box_the_picked_template_lacks_is_left_out(monkeypatch):
    _second_model_replies(monkeypatch, (
        '{"template_id": "drake", "texts": [{"box": "rejected_option", "caption": "a"}, '
        '{"box": "button_1", "caption": "x"}], "reasoning": "c"}'
    ))

    result = await parse_intent("anything")

    assert result.texts == {"rejected_option": "a"}


@pytest.mark.parametrize("texts", ["[]", '[{"box": "button_1", "caption": "x"}]', '[{"caption": "a"}]', '["a", "b"]'])
async def test_a_list_with_no_caption_for_the_picked_template_is_not_accepted(monkeypatch, texts):
    _second_model_replies(monkeypatch, '{"template_id": "drake", "texts": %s, "reasoning": "c"}' % texts)

    result = await parse_intent("anything")

    assert is_fallback(result)


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
    assert result.texts == {"rejected_option": "a", "approved_option": "b"}
    assert [(s["model"], s["response_format"]["type"]) for s in seen] == [
        (_PRIMARY, "json_object"),
        (_PRIMARY, "json_object"),
        (_SECOND, "json_schema"),
        (_SECOND, "json_object"),
    ]
