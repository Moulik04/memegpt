"""
Rate-limited photo calls. Every uploaded photo costs two vision calls
(safety check, then description or canvas captions), and a rate-limit
response on either used to end the upload on the spot: the safety check
failed closed and the user was told the image couldn't be processed.

Covered here, bottom to top:
  - call_groq_vision() waits and retries on a 429, for as long as the
    provider asks, within a fixed budget;
  - when the budget runs out the safety check still fails closed, but as
    "busy" rather than as a content refusal;
  - the upload routes say "busy, try again in a minute" for that case, and
    a real content refusal still wins over it.

Uses httpx.MockTransport, same as test_llm_client.py — no network call, and
the waits are recorded instead of slept.
"""

from __future__ import annotations

import io
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from config import Settings
from main import app
from nlp import vision
from nlp.vision import VisionBusy, VisionRateLimited, VisionUnavailable, call_groq_vision
from schemas import VisionDescription
from uploads import moderation
from uploads.safe_ingest import CleanImage, ModerationBusy, ModerationRejected, safe_ingest

_OK_BODY = {"choices": [{"message": {"content": "SAFE"}}]}


def _settings() -> Settings:
    return Settings(_env_file=None, groq_api_key="fake-key")


def _image() -> Image.Image:
    return Image.new("RGB", (10, 10), color="blue")


@pytest.fixture
def waits(monkeypatch) -> list[float]:
    """Every wait call_groq_vision() asks for, in order, without sleeping."""
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(vision.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(vision.random, "uniform", lambda low, high: 0.0)
    return recorded


def _serve(monkeypatch, responses: list[httpx.Response]) -> list[httpx.Request]:
    """Answer successive Groq calls from `responses`; the last one repeats."""
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


def _rate_limited(retry_after: str | None = "2") -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return httpx.Response(429, headers=headers, json={})


def _ok() -> httpx.Response:
    return httpx.Response(200, json=_OK_BODY)


async def _call() -> str:
    return await call_groq_vision(_image(), "system", "user", "some-model", _settings())


# --- call_groq_vision -------------------------------------------------------


async def test_a_rate_limited_call_waits_as_long_as_asked_then_succeeds(monkeypatch, waits):
    seen = _serve(monkeypatch, [_rate_limited("7"), _ok()])

    assert await _call() == "SAFE"
    assert len(seen) == 2
    assert waits == [7.0]


async def test_a_decimal_retry_after_is_honoured(monkeypatch, waits):
    _serve(monkeypatch, [_rate_limited("1.5"), _ok()])

    assert await _call() == "SAFE"
    assert waits == [1.5]


async def test_without_a_retry_after_the_wait_grows_each_time(monkeypatch, waits):
    _serve(monkeypatch, [_rate_limited(None), _rate_limited(None), _rate_limited("nonsense"), _ok()])

    assert await _call() == "SAFE"
    assert waits == [2.0, 4.0, 8.0]


async def test_retries_running_out_raises_rate_limited(monkeypatch, waits):
    seen = _serve(monkeypatch, [_rate_limited("1")])

    with pytest.raises(VisionRateLimited):
        await _call()
    assert len(seen) == vision._RATE_LIMIT_ATTEMPTS
    assert len(waits) == vision._RATE_LIMIT_ATTEMPTS - 1


async def test_a_wait_longer_than_the_budget_gives_up_without_sleeping(monkeypatch, waits):
    """Sleeping through a wait the budget cannot cover only delays the same
    answer."""
    seen = _serve(monkeypatch, [_rate_limited("600")])

    with pytest.raises(VisionRateLimited):
        await _call()
    assert len(seen) == 1
    assert waits == []


async def test_total_waiting_stays_inside_the_budget(monkeypatch, waits):
    _serve(monkeypatch, [_rate_limited("20")])

    with pytest.raises(VisionRateLimited):
        await _call()
    assert sum(waits) <= vision._RATE_LIMIT_WAIT_BUDGET_SECONDS


async def test_other_errors_are_not_retried(monkeypatch, waits):
    seen = _serve(monkeypatch, [httpx.Response(500, json={})])

    with pytest.raises(httpx.HTTPStatusError):
        await _call()
    assert len(seen) == 1
    assert waits == []


# --- safety check -----------------------------------------------------------


@pytest.fixture
def groq_key(monkeypatch):
    monkeypatch.setattr(moderation, "get_settings", _settings)
    monkeypatch.setattr(vision, "get_settings", _settings)


async def test_safety_check_passes_after_a_rate_limited_first_try(monkeypatch, waits, groq_key):
    _serve(monkeypatch, [_rate_limited("3"), _ok()])

    result = await moderation.moderate_image(_image())

    assert result.passed is True


async def test_safety_check_fails_closed_when_retries_run_out(monkeypatch, waits, groq_key):
    _serve(monkeypatch, [_rate_limited("1")])

    result = await moderation.moderate_image(_image())

    assert result.passed is False
    assert result.category == moderation.CATEGORY_RATE_LIMITED


async def test_safe_ingest_rejects_a_photo_it_could_not_check(monkeypatch, waits, groq_key, tiny_jpeg_upload):
    """Busy is still a rejection. Anything that only knows about
    ModerationRejected keeps treating it as one."""
    _serve(monkeypatch, [_rate_limited("1")])

    with pytest.raises(ModerationBusy) as excinfo:
        await safe_ingest(tiny_jpeg_upload)
    assert isinstance(excinfo.value, ModerationRejected)


# --- description and canvas captions ---------------------------------------


async def test_description_rate_limited_out_raises_busy(monkeypatch, waits, groq_key):
    _serve(monkeypatch, [_rate_limited("1")])

    with pytest.raises(VisionBusy) as excinfo:
        await vision.describe_image(_image())
    assert isinstance(excinfo.value, VisionUnavailable)


async def test_description_failing_for_another_reason_is_not_busy(monkeypatch, waits, groq_key):
    _serve(monkeypatch, [httpx.Response(500, json={})])

    with pytest.raises(VisionUnavailable) as excinfo:
        await vision.describe_image(_image())
    assert not isinstance(excinfo.value, VisionBusy)


async def test_canvas_captions_rate_limited_out_raises_busy(monkeypatch, waits, groq_key):
    _serve(monkeypatch, [_rate_limited("1")])

    with pytest.raises(VisionBusy):
        await vision.generate_canvas_captions(_image())


async def test_canvas_captions_failing_for_another_reason_still_returns_none(monkeypatch, waits, groq_key):
    _serve(monkeypatch, [httpx.Response(500, json={})])

    assert await vision.generate_canvas_captions(_image()) is None


# --- the upload routes ------------------------------------------------------

_BUSY = "MemeGPT is busy, try again in a minute."


def _tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    _image().save(buf, format="JPEG")
    return buf.getvalue()


async def _fake_safe_ingest(upload):
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
    return [json.loads(line[len("data: "):]) for line in resp.text.splitlines() if line.startswith("data: ")]


def _errors(events: list[dict]) -> list[str]:
    return [e["message"] for e in events if e.get("type") == "error"]


def _memes(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "done" and e["message"].get("meme_url")]


@pytest.fixture
def stub_ingest(monkeypatch):
    monkeypatch.setattr("routers.chat.safe_ingest", _fake_safe_ingest)


@pytest.mark.parametrize("path", ["/chat/image/", "/lore/image/"])
async def test_a_photo_that_could_not_be_checked_says_busy_not_refused(stub_ingest, path):
    events = await _post_images(["busy.jpg"], path=path)

    assert _errors(events) == [_BUSY]
    assert _memes(events) == []


async def test_one_unchecked_photo_holds_back_the_whole_upload(stub_ingest):
    """No meme is made from the photos that did pass: the person asked for
    all of them, and a retry in a minute gets all of them."""
    events = await _post_images(["clean.jpg", "busy.jpg"])

    assert _errors(events) == [_BUSY]
    assert _memes(events) == []


async def test_a_real_refusal_wins_over_busy(stub_ingest):
    events = await _post_images(["busy.jpg", "flagged.jpg"])

    assert len(_errors(events)) == 1
    assert "couldn't be processed" in _errors(events)[0]


async def test_description_busy_for_every_photo_says_busy(stub_ingest, monkeypatch):
    async def busy_describe(image, user_text=None):
        raise VisionBusy("rate limited")

    monkeypatch.setattr("routers.chat.describe_image", busy_describe)

    events = await _post_images(["clean.jpg", "clean2.jpg"])

    assert _errors(events) == [_BUSY]
    assert [e for e in events if e.get("type") == "done"] == []


async def test_description_unavailable_for_another_reason_still_asks_for_words(stub_ingest, monkeypatch):
    async def broken_describe(image, user_text=None):
        raise VisionUnavailable("provider down")

    monkeypatch.setattr("routers.chat.describe_image", broken_describe)

    events = await _post_images(["clean.jpg"])

    assert _errors(events) == []
    replies = [e["message"]["content"] for e in events if e.get("type") == "done"]
    assert len(replies) == 1 and "describing" in replies[0]


async def test_canvas_captions_busy_for_every_photo_says_busy(stub_ingest, monkeypatch):
    async def busy_captions(image, user_text=None):
        raise VisionBusy("rate limited")

    monkeypatch.setattr("routers.chat.generate_canvas_captions", busy_captions)

    events = await _post_images(["clean.jpg"], message="make this a meme")

    assert _errors(events) == [_BUSY]
    assert _memes(events) == []


async def test_canvas_keeps_the_photos_that_got_captions(stub_ingest, monkeypatch):
    calls = {"n": 0}

    async def first_busy_then_fine(image, user_text=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise VisionBusy("rate limited")
        return {"top_text": "TOP", "bottom_text": "BOTTOM"}

    monkeypatch.setattr("routers.chat.generate_canvas_captions", first_busy_then_fine)

    events = await _post_images(["clean.jpg", "clean2.jpg"], message="make this a meme")

    assert _errors(events) == []
    assert len(_memes(events)) == 1


async def test_an_upload_gets_a_first_event_before_any_photo_call(stub_ingest, monkeypatch):
    """A rate-limited check can now hold the stream for a while. Something
    has to go out first, or a proxy in front of the backend sees a silent
    connection."""
    async def describe(image, user_text=None):
        return VisionDescription(situation="a fake photo description")

    monkeypatch.setattr("routers.chat.describe_image", describe)

    events = await _post_images(["busy.jpg"])

    assert events[0]["type"] == "thinking"
