"""
A per-minute rate limit is waited out, not answered around.

Groq's per-minute limit clears in seconds. The router used to give up on it
after two short waits and ask again with its strict retry prompt, which at
the time listed fourteen templates and no descriptions, so a busy minute
quietly produced worse memes. Now:

  - the router's Groq call waits as long as Groq says and sends the same
    prompt again, as many times as the request's deadline allows;
  - if a wait would run past the deadline nothing more is sent, and the
    visitor is told MemeGPT is busy instead of being shown a canned meme;
  - a rate limit never moves the pick to the retry prompt or to the second
    model (the daily cap still does, see test_daily_budget.py);
  - the retry prompt, reached only by an unusable reply, offers the same
    candidates with the same descriptions as the first attempt;
  - every pick records which prompt and which model answered.

Uses httpx.MockTransport, same as test_llm_client.py. No network call.
"""

from __future__ import annotations

import json
import logging
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import circuit_breaker as cb
import telemetry
from config import Settings
from main import app
from nlp import intent_router, llm_client
from nlp.intent_router import (
    USE_WHEN,
    _build_retry_prompt,
    is_busy_fallback,
    is_daily_budget_fallback,
    is_fallback,
    parse_intent,
)
from nlp.llm_client import RateLimited, call_groq, daily_limit_active
from schemas import IntentResponse

_BUSY = "MemeGPT is busy, try again in a minute."
_PRIMARY = "qwen/qwen3.8-27b"
_SECOND = "openai/gpt-oss-120b"
_MESSAGES = [{"role": "system", "content": "the full prompt"}, {"role": "user", "content": "hi"}]
_DRAKE = '{"template_id": "drake", "texts": {"rejected_option": "a", "preferred_option": "b"}}'


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="groq",
        groq_api_key="fake-key",
        groq_model=_PRIMARY,
        groq_fallback_model=_SECOND,
    )


def _minute_429(retry_after: str | None = "0") -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    body = {"error": {"message": "Rate limit reached on tokens per minute (TPM): Limit 8000."}}
    return httpx.Response(429, headers=headers, json=body)


def _daily_429() -> httpx.Response:
    body = {"error": {"message": "Rate limit reached on tokens per day (TPD): Limit 200000."}}
    return httpx.Response(429, headers={"retry-after": "1252"}, json=body)


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})


def _client(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen), len(responses)) - 1]

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def no_sleep(monkeypatch) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(llm_client.asyncio, "sleep", fake_sleep)
    return slept


@pytest.fixture
def picks(monkeypatch) -> list[tuple]:
    seen: list[tuple] = []
    monkeypatch.setattr(telemetry, "record_router_pick", lambda prompt, model, template_id: seen.append((prompt, model, template_id)))
    return seen


# --- the Groq call, given a deadline ------------------------------------------


async def test_the_wait_groq_asks_for_is_taken_in_full_and_the_same_prompt_sent_again(no_sleep):
    seen: list[httpx.Request] = []
    async with _client([_minute_429("21.5"), _ok()], seen) as client:
        result = await call_groq(client, _settings(), _MESSAGES, wait_until=time.monotonic() + 40)

    assert result == "hello"
    assert no_sleep == [21.5]
    assert [json.loads(r.content)["messages"] for r in seen] == [_MESSAGES, _MESSAGES]


async def test_every_rate_limit_is_waited_out_while_the_deadline_allows(no_sleep):
    seen: list[httpx.Request] = []
    responses = [_minute_429("5"), _minute_429("7"), _minute_429("3"), _ok()]
    async with _client(responses, seen) as client:
        result = await call_groq(client, _settings(), _MESSAGES, wait_until=time.monotonic() + 40)

    assert result == "hello"
    assert no_sleep == [5, 7, 3]
    assert len(seen) == 4


async def test_a_wait_that_would_pass_the_deadline_is_not_started(no_sleep):
    seen: list[httpx.Request] = []
    async with _client([_minute_429("30")], seen) as client:
        with pytest.raises(RateLimited) as raised:
            await call_groq(client, _settings(), _MESSAGES, wait_until=time.monotonic() + 10)

    assert raised.value.retry_after == 30
    assert no_sleep == []
    assert len(seen) == 1


async def test_a_rate_limit_that_names_no_wait_still_waits_before_asking_again(no_sleep):
    seen: list[httpx.Request] = []
    async with _client([_minute_429(None), _ok()], seen) as client:
        result = await call_groq(client, _settings(), _MESSAGES, wait_until=time.monotonic() + 40)

    assert result == "hello"
    assert no_sleep == [3]


async def test_a_zero_wait_does_not_become_a_tight_loop(no_sleep):
    seen: list[httpx.Request] = []
    async with _client([_minute_429("0"), _minute_429("0"), _ok()], seen) as client:
        result = await call_groq(client, _settings(), _MESSAGES, wait_until=time.monotonic() + 40)

    assert result == "hello"
    assert no_sleep == [1, 1]


async def test_the_daily_cap_is_not_waited_on_even_with_a_deadline(no_sleep):
    seen: list[httpx.Request] = []
    async with _client([_daily_429()], seen) as client:
        result = await call_groq(client, _settings(), _MESSAGES, wait_until=time.monotonic() + 40)

    assert result == ""
    assert no_sleep == []
    assert daily_limit_active(_PRIMARY) is True


# --- the router -----------------------------------------------------------------


async def test_a_rate_limit_that_cannot_be_waited_out_says_busy_and_asks_nobody_else(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    asked: list[str] = []

    async def rate_limited(client, settings, messages, temperature=0.75, **kwargs):
        asked.append(settings.groq_model)
        raise RateLimited(30)

    monkeypatch.setattr(intent_router, "call_llm", rate_limited)

    result = await parse_intent("anything")

    assert is_busy_fallback(result)
    assert is_fallback(result)
    assert not is_daily_budget_fallback(result)
    assert asked == [_PRIMARY]  # no retry prompt, no second model


async def test_the_router_gives_groq_a_deadline_inside_its_own_time_limit(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    deadlines: list[float] = []

    async def answers(client, settings, messages, temperature=0.75, **kwargs):
        deadlines.append(kwargs["wait_until"])
        return _DRAKE

    monkeypatch.setattr(intent_router, "call_llm", answers)

    before = time.monotonic()
    await parse_intent("anything")

    assert len(deadlines) == 1
    assert before < deadlines[0] < before + intent_router._OVERALL_TIMEOUT_SECONDS


async def test_a_per_minute_trip_does_not_move_the_pick_to_the_second_model(monkeypatch):
    """Another caller (segmentation, say) exhausting its own short waits
    opens the model's circuit for a minute. The router used to read that as
    "skip to the second model", which only ever gets the retry prompt."""
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    cb.trip(f"groq:{_PRIMARY}", cooldown_seconds=60)
    asked: list[str] = []

    async def answers(client, settings, messages, temperature=0.75, **kwargs):
        asked.append(settings.groq_model)
        return _DRAKE

    monkeypatch.setattr(intent_router, "call_llm", answers)

    result = await parse_intent("anything")

    assert asked == [_PRIMARY]
    assert result.template_id == "drake"


async def test_a_rate_limited_first_attempt_is_answered_by_the_full_prompt_end_to_end(monkeypatch, no_sleep, picks):
    """Router and Groq call together, with only the network faked: the 429
    is waited out and the full prompt is what gets answered."""
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    seen: list[httpx.Request] = []
    pick = httpx.Response(200, json={"choices": [{"message": {"content": _DRAKE}}]})
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return [_minute_429("12.5"), pick][min(len(seen), 2) - 1]

    monkeypatch.setattr(
        intent_router.httpx, "AsyncClient", lambda: real_client(transport=httpx.MockTransport(handler))
    )

    result = await parse_intent("anything")

    assert result.template_id == "drake"
    assert no_sleep == [12.5]
    sent = [json.loads(r.content) for r in seen]
    assert len(sent) == 2 and sent[0]["messages"] == sent[1]["messages"]
    assert sent[0]["messages"][0]["role"] == "system"  # the full prompt, both times
    assert {s["model"] for s in sent} == {_PRIMARY}
    assert picks == [("full", "primary", "drake")]


# --- the retry prompt -------------------------------------------------------------


def test_the_retry_prompt_offers_every_candidate_with_its_description():
    ids = intent_router._CORE_TEMPLATE_IDS + ["domino_effect", "absolute_cinema", "megamind_no_bitches"]

    prompt = _build_retry_prompt("anything", ids)

    for template_id in ids:
        assert f'"{template_id}"' in prompt, template_id
        assert json.dumps(USE_WHEN[template_id]) in prompt, template_id
    assert "rejected_option" in prompt  # box labels are still there


async def test_a_retry_sees_the_same_candidates_as_the_first_attempt(monkeypatch):
    ids = intent_router._CORE_TEMPLATE_IDS + ["domino_effect", "absolute_cinema"]

    async def fixed_candidates(user_message, known_id_set):
        return list(ids)

    prompts: list[str] = []

    async def unusable_then_fine(client, settings, messages, temperature=0.75, **kwargs):
        prompts.append(" ".join(m["content"] for m in messages))
        return "not valid json" if len(prompts) == 1 else _DRAKE

    monkeypatch.setattr(intent_router, "resolve_prompt_template_ids", fixed_candidates)
    monkeypatch.setattr(intent_router, "call_llm", unusable_then_fine)

    await parse_intent("anything")

    first, retry = prompts
    for template_id in ids:
        assert f'"{template_id}"' in first, template_id
        assert f'"{template_id}"' in retry, template_id
        assert json.dumps(USE_WHEN[template_id]) in retry, template_id


# --- which prompt answered ---------------------------------------------------------


async def test_a_first_attempt_pick_is_recorded_as_the_full_prompt(monkeypatch, picks):
    monkeypatch.setattr(intent_router, "get_settings", _settings)

    async def answers(client, settings, messages, temperature=0.75, **kwargs):
        return _DRAKE

    monkeypatch.setattr(intent_router, "call_llm", answers)

    result = await parse_intent("anything")

    assert (result.prompt_used, result.model_used) == ("full", "primary")
    assert picks == [("full", "primary", "drake")]


async def test_a_pick_made_after_an_unusable_reply_is_recorded_as_the_retry_prompt(monkeypatch, picks):
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    replies = iter(["not valid json", _DRAKE])

    async def unusable_then_fine(client, settings, messages, temperature=0.75, **kwargs):
        return next(replies)

    monkeypatch.setattr(intent_router, "call_llm", unusable_then_fine)

    result = await parse_intent("anything")

    assert (result.prompt_used, result.model_used) == ("retry", "primary")
    assert picks == [("retry", "primary", "drake")]


async def test_a_second_model_pick_is_recorded_as_such(monkeypatch, picks):
    monkeypatch.setattr(intent_router, "get_settings", _settings)

    async def only_the_second_model_answers(client, settings, messages, temperature=0.75, **kwargs):
        return _DRAKE if settings.groq_model == _SECOND else "not valid json"

    monkeypatch.setattr(intent_router, "call_llm", only_the_second_model_answers)

    result = await parse_intent("anything")

    assert (result.prompt_used, result.model_used) == ("retry", "second")
    assert picks == [("retry", "second", "drake")]


async def test_a_canned_fallback_records_no_pick(monkeypatch, picks):
    monkeypatch.setattr(intent_router, "get_settings", _settings)

    async def never_usable(client, settings, messages, temperature=0.75, **kwargs):
        return "not valid json"

    monkeypatch.setattr(intent_router, "call_llm", never_usable)

    result = await parse_intent("anything")

    assert is_fallback(result)
    assert (result.prompt_used, result.model_used) == (None, None)
    assert picks == []


async def test_a_reply_cannot_name_its_own_prompt(monkeypatch, picks):
    """The record is the router's, not something the model can write."""

    async def claims_the_full_prompt(client, settings, messages, temperature=0.75, **kwargs):
        if len(messages) == 2:
            return "not valid json"
        return _DRAKE[:-1] + ', "prompt_used": "full", "model_used": "second"}'

    monkeypatch.setattr(intent_router, "call_llm", claims_the_full_prompt)

    result = await parse_intent("anything")

    assert (result.prompt_used, result.model_used) == ("retry", "primary")


def test_the_record_never_leaves_with_the_pick():
    pick = IntentResponse(template_id="drake", texts={"rejected_option": "a"}, prompt_used="full", model_used="primary")

    assert set(pick.model_dump()) == {"template_id", "texts", "reasoning"}


def test_a_pick_is_written_to_the_log_as_one_line(caplog):
    with caplog.at_level(logging.WARNING, logger="telemetry"):
        telemetry.record_router_pick("retry", "primary", "drake")

    assert [r.getMessage() for r in caplog.records] == ["router_pick prompt=retry model=primary template=drake"]


def test_a_busy_answer_is_written_to_the_log_as_one_line(caplog):
    with caplog.at_level(logging.WARNING, logger="telemetry"):
        telemetry.record_router_busy(26.4)

    assert [r.getMessage() for r in caplog.records] == ["router_busy retry_after=27s"]


# --- Chat and Lore -----------------------------------------------------------------


def _events(raw_text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in raw_text.splitlines() if line.startswith("data: ")]


async def _busy_intent(user_message, **kwargs) -> IntentResponse:
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={"top_text": user_message[:60], "bottom_text": "This is fine."},
        reasoning=intent_router.BUSY_FALLBACK_REASONING,
    )


async def test_chat_says_busy_instead_of_showing_a_canned_meme(monkeypatch):
    async def must_not_render(**kwargs):
        raise AssertionError("no meme is rendered when the pick could not be made")

    monkeypatch.setattr("routers.chat.parse_intent", _busy_intent)
    monkeypatch.setattr("routers.chat.compose_meme", must_not_render)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat/", json={"message": "waiting for my PR to get reviewed"})

    events = _events(resp.text)
    assert [(e["message"], e["reason"]) for e in events if e["type"] == "error"] == [(_BUSY, "busy")]
    assert [e for e in events if e["type"] == "done"] == []
    assert events[-1] == {"type": "batch_done", "total": 1, "succeeded": 0}


async def test_a_lore_batch_carries_on_after_a_busy_meme(monkeypatch):
    """Unlike the daily cap, a busy minute passes: the next moment gets its
    own wait and its own chance."""
    asked: list[str] = []

    async def second_one_is_busy(user_message, **kwargs) -> IntentResponse:
        asked.append(user_message)
        if len(asked) == 2:
            return await _busy_intent(user_message)
        return IntentResponse(template_id="drake", texts={"rejected_option": "a"}, reasoning="a pick")

    async def three_moments(client, settings, messages, temperature=0.75, max_tokens=None):
        return json.dumps({"contexts": [
            {"situation": "the landlord raised the rent again"},
            {"situation": "my flight got cancelled at the gate"},
            {"situation": "the cat knocked over the monitor"},
        ]})

    monkeypatch.setattr("nlp.segmentation.call_llm", three_moments)
    monkeypatch.setattr("routers.chat.parse_intent", second_one_is_busy)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/lore/", json={"message": "a long paste", "meme_count": 3})

    events = _events(resp.text)
    assert len(asked) == 3
    assert [e["index"] for e in events if e["type"] == "done"] == [0, 2]
    assert [(e["message"], e["index"]) for e in events if e["type"] == "error"] == [(_BUSY, 1)]
    assert events[-1] == {"type": "batch_done", "total": 3, "succeeded": 2}
