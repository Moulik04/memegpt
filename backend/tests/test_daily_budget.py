"""
Groq's daily cap, told apart from its per-minute one.

Both arrive as a 429. The per-minute window frees up in seconds, so waiting
and "busy, try again in a minute" are right for it. The daily budget takes
hours to come back: waiting is pointless, and the person should be told
what actually happened instead of getting a canned meme or "a minute".

Covered here, bottom to top:
  - a 429 is recognised as the daily cap from what Groq says about it;
  - once a model is known to be out for the day it is not called again
    until Groq said to come back, by the text calls or the photo calls;
  - the router's hard fallback says the budget is why;
  - Chat, Lore, photo uploads and Make each show the daily wording for that
    case and keep "busy" for the per-minute one.

Uses httpx.MockTransport, same as test_llm_client.py. No network call.
"""

from __future__ import annotations

import io
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

import routers.generate as generate_router
from config import Settings
from main import app
from nlp import intent_router, llm_client, text_moderation, vision
from nlp.intent_router import is_daily_budget_fallback, is_fallback, parse_intent
from nlp.llm_client import call_groq, daily_limit_active, daily_limit_cooldown, mark_daily_limit
from nlp.vision import (
    VisionBusy,
    VisionDailyLimited,
    VisionOutOfBudget,
    VisionRateLimited,
    call_groq_vision,
)
from schemas import IntentResponse
from uploads import moderation
from uploads.safe_ingest import (
    CleanImage,
    ModerationBusy,
    ModerationOutOfBudget,
    ModerationRejected,
    safe_ingest,
)

_DAILY = (
    "MemeGPT runs on a free daily AI budget, and today's is used up. "
    "It refills gradually, so try again in a few hours."
)
_BUSY = "MemeGPT is busy, try again in a minute."

_MODEL = "qwen/qwen3.8-27b"

# The shape Groq answered with when the cap was reached on 2026-10-07.
_DAILY_BODY = {
    "error": {
        "message": (
            f"Rate limit reached for model `{_MODEL}` on tokens per day (TPD): "
            "Limit 200000, Used 199000, Requested 2900. Please try again in 20m52s."
        ),
        "type": "tokens",
        "code": "rate_limit_exceeded",
    }
}
_MINUTE_BODY = {
    "error": {
        "message": (
            f"Rate limit reached for model `{_MODEL}` on tokens per minute (TPM): "
            "Limit 8000, Used 7000, Requested 2900. Please try again in 6.5s."
        ),
        "type": "tokens",
        "code": "rate_limit_exceeded",
    }
}


def _daily_429(retry_after: str | None = "1252") -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return httpx.Response(429, headers=headers, json=_DAILY_BODY)


def _minute_429(retry_after: str = "0") -> httpx.Response:
    return httpx.Response(429, headers={"retry-after": retry_after}, json=_MINUTE_BODY)


def _settings() -> Settings:
    return Settings(_env_file=None, llm_provider="groq", groq_api_key="fake-key", groq_model=_MODEL)


def _image() -> Image.Image:
    return Image.new("RGB", (10, 10), color="blue")


# --- recognising the daily cap ----------------------------------------------


def test_a_429_naming_the_daily_limit_is_the_daily_cap():
    assert daily_limit_cooldown(_daily_429("1252")) == 1252


def test_a_per_minute_429_is_not():
    assert daily_limit_cooldown(_minute_429("6.5")) is None


def test_a_wait_far_longer_than_a_minute_is_the_daily_cap_whatever_the_body_says():
    """The per-minute window never needs minutes to free up."""
    assert daily_limit_cooldown(httpx.Response(429, headers={"retry-after": "900"}, json={})) == 900


def test_a_daily_429_without_a_usable_wait_still_keeps_off_the_model():
    assert daily_limit_cooldown(_daily_429(None)) == llm_client._DAILY_LIMIT_DEFAULT_COOLDOWN_SECONDS
    assert daily_limit_cooldown(_daily_429("soon")) == llm_client._DAILY_LIMIT_DEFAULT_COOLDOWN_SECONDS


def test_the_time_off_a_model_is_bounded():
    """One odd header must not keep a model switched off for days."""
    assert daily_limit_cooldown(_daily_429("999999")) == llm_client._DAILY_LIMIT_MAX_COOLDOWN_SECONDS


def test_other_statuses_are_never_the_daily_cap():
    assert daily_limit_cooldown(httpx.Response(500, json=_DAILY_BODY)) is None


# --- text calls --------------------------------------------------------------


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
    monkeypatch.setattr(vision.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(vision.random, "uniform", lambda low, high: 0.0)
    return slept


async def test_the_daily_cap_is_not_waited_out_or_retried(no_sleep):
    seen: list[httpx.Request] = []
    async with _client([_daily_429()], seen) as client:
        result = await call_groq(client, _settings(), [{"role": "user", "content": "hi"}])

    assert result == ""
    assert len(seen) == 1
    assert no_sleep == []
    assert daily_limit_active(_MODEL) is True


async def test_a_model_out_for_the_day_is_not_called_again(no_sleep):
    mark_daily_limit(_MODEL, 600)
    seen: list[httpx.Request] = []
    async with _client([httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})], seen) as client:
        result = await call_groq(client, _settings(), [{"role": "user", "content": "hi"}])

    assert result == ""
    assert seen == []


async def test_the_daily_cap_on_one_model_leaves_another_alone():
    mark_daily_limit(_MODEL, 600)

    assert daily_limit_active(_MODEL) is True
    assert daily_limit_active("openai/gpt-oss-120b") is False


async def test_a_per_minute_429_is_still_waited_out_and_is_not_the_daily_cap(no_sleep):
    seen: list[httpx.Request] = []
    async with _client([_minute_429("2")], seen) as client:
        result = await call_groq(client, _settings(), [{"role": "user", "content": "hi"}])

    assert result == ""
    assert len(seen) == 2
    assert no_sleep == [2, 2]
    assert daily_limit_active(_MODEL) is False


async def test_a_decimal_retry_after_does_not_break_the_text_call(no_sleep):
    seen: list[httpx.Request] = []
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})
    async with _client([_minute_429("6.5"), ok], seen) as client:
        result = await call_groq(client, _settings(), [{"role": "user", "content": "hi"}])

    assert result == "hello"
    assert no_sleep == [6.5]


# --- the router's hard fallback ---------------------------------------------


async def _llm_with_nothing_to_say(client, settings, messages, temperature=0.75, max_tokens=None):
    return ""


async def test_hard_fallback_says_so_when_the_budget_is_why(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    monkeypatch.setattr(intent_router, "call_llm", _llm_with_nothing_to_say)
    mark_daily_limit(_MODEL, 600)

    result = await parse_intent("anything")

    assert is_daily_budget_fallback(result)
    assert is_fallback(result)


async def test_hard_fallback_for_any_other_reason_does_not_blame_the_budget(monkeypatch):
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    monkeypatch.setattr(intent_router, "call_llm", _llm_with_nothing_to_say)

    result = await parse_intent("anything")

    assert is_fallback(result)
    assert not is_daily_budget_fallback(result)


async def test_a_real_pick_from_the_second_model_is_still_a_real_pick(monkeypatch):
    """The second model has a daily budget of its own. While it answers,
    people keep getting memes and nobody is told the budget is gone."""
    monkeypatch.setattr(intent_router, "get_settings", _settings)
    mark_daily_limit(_MODEL, 600)
    asked: list[str] = []

    async def second_model_answers(client, settings, messages, temperature=0.75, max_tokens=None):
        asked.append(settings.groq_model)
        return '{"template_id": "drake", "texts": {"rejected_option": "a"}}'

    monkeypatch.setattr(intent_router, "call_llm", second_model_answers)

    result = await parse_intent("anything")

    assert asked == ["openai/gpt-oss-120b"]
    assert result.template_id == "drake"
    assert not is_fallback(result)


# --- Chat and Lore -----------------------------------------------------------


def _events(raw_text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in raw_text.splitlines() if line.startswith("data: ")]


async def _out_of_budget_intent(user_message, **kwargs) -> IntentResponse:
    return IntentResponse(
        template_id="hide_the_pain_harold",
        texts={"top_text": user_message[:60], "bottom_text": "This is fine."},
        reasoning=intent_router.DAILY_BUDGET_FALLBACK_REASONING,
    )


async def test_chat_says_the_budget_is_used_up_instead_of_a_canned_meme(monkeypatch):
    async def must_not_render(**kwargs):
        raise AssertionError("no meme is rendered when the budget is used up")

    monkeypatch.setattr("routers.chat.parse_intent", _out_of_budget_intent)
    monkeypatch.setattr("routers.chat.compose_meme", must_not_render)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/chat/", json={"message": "waiting for my PR to get reviewed"})

    events = _events(resp.text)
    assert [e["message"] for e in events if e["type"] == "error"] == [_DAILY]
    assert [e for e in events if e["type"] == "done"] == []
    assert events[-1] == {"type": "batch_done", "total": 1, "succeeded": 0}


async def test_a_lore_batch_stops_at_the_first_meme_the_budget_could_not_cover(monkeypatch):
    """The remaining picks would only fail the same way, one message each."""
    asked: list[str] = []

    async def first_pick_only(user_message, **kwargs) -> IntentResponse:
        asked.append(user_message)
        if len(asked) == 1:
            return IntentResponse(template_id="drake", texts={"rejected_option": "a"}, reasoning="a pick")
        return await _out_of_budget_intent(user_message)

    async def three_moments(client, settings, messages, temperature=0.75, max_tokens=None):
        return json.dumps({"contexts": [
            {"situation": "the landlord raised the rent again"},
            {"situation": "my flight got cancelled at the gate"},
            {"situation": "the cat knocked over the monitor"},
        ]})

    monkeypatch.setattr("nlp.segmentation.call_llm", three_moments)
    monkeypatch.setattr("routers.chat.parse_intent", first_pick_only)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/lore/", json={"message": "a long paste", "meme_count": 3})

    events = _events(resp.text)
    assert len(asked) == 2
    assert [e["index"] for e in events if e["type"] == "done"] == [0]
    assert [e["message"] for e in events if e["type"] == "error"] == [_DAILY]
    assert events[-1] == {"type": "batch_done", "total": 3, "succeeded": 1}


# --- photo calls -------------------------------------------------------------


def _serve_vision(monkeypatch, responses: list[httpx.Response]) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen), len(responses)) - 1]

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(vision.httpx, "AsyncClient", client_factory)
    return seen


@pytest.fixture
def groq_key(monkeypatch):
    monkeypatch.setattr(moderation, "get_settings", _settings)
    monkeypatch.setattr(vision, "get_settings", _settings)
    monkeypatch.setattr(text_moderation, "get_settings", _settings)


async def test_a_photo_call_gives_up_at_once_on_the_daily_cap(monkeypatch, no_sleep):
    seen = _serve_vision(monkeypatch, [_daily_429()])

    with pytest.raises(VisionDailyLimited) as excinfo:
        await call_groq_vision(_image(), "system", "user", _MODEL, _settings())

    assert isinstance(excinfo.value, VisionRateLimited)
    assert len(seen) == 1
    assert no_sleep == []
    assert daily_limit_active(_MODEL) is True


async def test_a_photo_is_not_sent_to_a_model_that_is_out_for_the_day(monkeypatch, no_sleep):
    mark_daily_limit(_MODEL, 600)
    seen = _serve_vision(monkeypatch, [httpx.Response(200, json={"choices": [{"message": {"content": "SAFE"}}]})])

    with pytest.raises(VisionDailyLimited):
        await call_groq_vision(_image(), "system", "user", _MODEL, _settings())

    assert seen == []


async def test_safety_check_fails_closed_on_the_daily_cap(monkeypatch, no_sleep, groq_key, tiny_jpeg_upload):
    """Out of budget is still a rejection: the photo was never checked."""
    _serve_vision(monkeypatch, [_daily_429()])

    result = await moderation.moderate_image(_image())
    assert result.passed is False
    assert result.category == moderation.CATEGORY_DAILY_LIMIT

    with pytest.raises(ModerationOutOfBudget) as excinfo:
        await safe_ingest(tiny_jpeg_upload)
    assert isinstance(excinfo.value, ModerationBusy)
    assert isinstance(excinfo.value, ModerationRejected)


async def test_description_on_the_daily_cap_raises_out_of_budget(monkeypatch, no_sleep, groq_key):
    _serve_vision(monkeypatch, [_daily_429()])

    with pytest.raises(VisionOutOfBudget) as excinfo:
        await vision.describe_image(_image())
    assert isinstance(excinfo.value, VisionBusy)


async def test_canvas_captions_on_the_daily_cap_raise_out_of_budget(monkeypatch, no_sleep, groq_key):
    _serve_vision(monkeypatch, [_daily_429()])

    with pytest.raises(VisionOutOfBudget):
        await vision.generate_canvas_captions(_image())


# --- the upload routes -------------------------------------------------------


def _tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    _image().save(buf, format="JPEG")
    return buf.getvalue()


async def _fake_safe_ingest(upload):
    if upload.filename == "out_of_budget.jpg":
        raise ModerationOutOfBudget()
    if upload.filename == "busy.jpg":
        raise ModerationBusy()
    if upload.filename == "flagged.jpg":
        raise ModerationRejected(category="test_category")
    return CleanImage(
        image=_image(), width=10, height=10, content_type="image/jpeg", source_filename=upload.filename
    )


async def _post_images(names: list[str], *, path: str = "/chat/image/", **form_fields) -> list[dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            path,
            files=[("images", (name, _tiny_jpeg_bytes(), "image/jpeg")) for name in names],
            data={k: str(v) for k, v in form_fields.items()},
        )
    assert resp.status_code == 200
    return _events(resp.text)


def _errors(events: list[dict]) -> list[str]:
    return [e["message"] for e in events if e.get("type") == "error"]


@pytest.fixture
def stub_ingest(monkeypatch):
    monkeypatch.setattr("routers.chat.safe_ingest", _fake_safe_ingest)


@pytest.mark.parametrize("path", ["/chat/image/", "/lore/image/"])
async def test_a_photo_the_budget_could_not_check_gets_the_daily_wording(stub_ingest, path):
    events = await _post_images(["out_of_budget.jpg"], path=path)

    assert _errors(events) == [_DAILY]


async def test_the_daily_wording_wins_over_busy(stub_ingest):
    """Trying again in a minute would not help."""
    events = await _post_images(["busy.jpg", "out_of_budget.jpg"])

    assert _errors(events) == [_DAILY]


async def test_a_real_refusal_still_wins_over_the_daily_wording(stub_ingest):
    events = await _post_images(["out_of_budget.jpg", "flagged.jpg"])

    assert len(_errors(events)) == 1
    assert "can't use this image" in _errors(events)[0]


async def test_description_out_of_budget_gets_the_daily_wording(stub_ingest, monkeypatch):
    async def out_of_budget(image, user_text=None):
        raise VisionOutOfBudget("daily limit")

    monkeypatch.setattr("routers.chat.describe_image", out_of_budget)

    events = await _post_images(["clean.jpg"])

    assert _errors(events) == [_DAILY]
    assert [e for e in events if e.get("type") == "done"] == []


async def test_canvas_captions_out_of_budget_get_the_daily_wording(stub_ingest, monkeypatch):
    async def out_of_budget(image, user_text=None):
        raise VisionOutOfBudget("daily limit")

    monkeypatch.setattr("routers.chat.generate_canvas_captions", out_of_budget)

    events = await _post_images(["clean.jpg"], message="make this a meme")

    assert _errors(events) == [_DAILY]


# --- Make --------------------------------------------------------------------


def _serve_text_moderation(monkeypatch, response: httpx.Response) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(text_moderation.httpx, "AsyncClient", client_factory)
    return seen


async def _post_generate():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/generate/",
            json={"template_id": "drake", "texts": {"rejected_option": "a", "approved_option": "b"}},
        )


async def test_make_gets_the_daily_wording_and_renders_nothing(monkeypatch, groq_key):
    async def must_not_render(**kwargs):
        raise AssertionError("an unchecked caption must not be rendered")

    monkeypatch.setattr(generate_router, "compose_meme", must_not_render)
    _serve_text_moderation(monkeypatch, _daily_429())

    resp = await _post_generate()

    assert resp.status_code == 503
    assert resp.json()["detail"] == _DAILY
    assert daily_limit_active(_MODEL) is True


async def test_make_says_busy_for_the_per_minute_case(monkeypatch, groq_key):
    async def must_not_render(**kwargs):
        raise AssertionError("an unchecked caption must not be rendered")

    monkeypatch.setattr(generate_router, "compose_meme", must_not_render)
    _serve_text_moderation(monkeypatch, _minute_429("6.5"))

    resp = await _post_generate()

    assert resp.status_code == 503
    assert resp.json()["detail"] == _BUSY


async def test_make_does_not_call_a_model_that_is_out_for_the_day(monkeypatch, groq_key):
    mark_daily_limit(_MODEL, 600)
    seen = _serve_text_moderation(monkeypatch, httpx.Response(200, json={"choices": [{"message": {"content": "SAFE"}}]}))

    resp = await _post_generate()

    assert resp.status_code == 503
    assert resp.json()["detail"] == _DAILY
    assert seen == []


async def test_a_refused_caption_still_gets_the_generic_refusal(monkeypatch, groq_key):
    _serve_text_moderation(
        monkeypatch, httpx.Response(200, json={"choices": [{"message": {"content": "UNSAFE: hate"}}]})
    )

    resp = await _post_generate()

    assert resp.status_code == 400
    assert "hate" not in resp.text
